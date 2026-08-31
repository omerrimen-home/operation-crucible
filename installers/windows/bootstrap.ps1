#requires -version 5.1

Set-StrictMode -Version Latest

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$StateRoot = Join-Path -Path $env:ProgramData -ChildPath "Crucible"
$LogPath = Join-Path -Path $StateRoot -ChildPath "bootstrap.log"
$CompletePath = Join-Path -Path $StateRoot -ChildPath "bootstrap-complete"
$FailurePath = Join-Path -Path $StateRoot -ChildPath "bootstrap-failed"

$PersistentBootstrapPath = Join-Path `
    -Path $StateRoot `
    -ChildPath "bootstrap.ps1"

$PersistentConfigPath = Join-Path `
    -Path $StateRoot `
    -ChildPath "crucible-bootstrap.json"

$WindowsUpdateCompletePath = Join-Path `
    -Path $StateRoot `
    -ChildPath "windows-update-complete"

$WindowsUpdateCyclePath = Join-Path `
    -Path $StateRoot `
    -ChildPath "windows-update-cycle"

$BootstrapResumeTaskName = (
    "Operation Crucible Bootstrap Resume"
)

$MaxWindowsUpdateReboots = 6

$TranscriptStarted = $false
$BootstrapExitCode = 0


function Write-CrucibleLog {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Message
    )

    $Timestamp = (Get-Date).ToString("o")

    Write-Host ("[{0}] {1}" -f $Timestamp, $Message)
}


function Normalize-MacAddress {
    param(
        [Parameter(Mandatory = $true)]
        [string] $MacAddress
    )

    return $MacAddress.Replace(":", "").Replace("-", "").ToUpperInvariant()
}

function Find-CrucibleNetAdapterByMac {
    param(
        [Parameter(Mandatory = $true)]
        [string] $MacAddress,

        [Parameter(Mandatory = $false)]
        [string] $Description = "network",

        [Parameter(Mandatory = $false)]
        [int] $Attempts = 30
    )

    $TargetMac = Normalize-MacAddress $MacAddress

    for ($Attempt = 1; $Attempt -le $Attempts; $Attempt++) {

        $Adapters = Get-NetAdapter `
            -ErrorAction SilentlyContinue

        foreach ($Adapter in $Adapters) {

            $AdapterMac = Normalize-MacAddress `
                ([string]$Adapter.MacAddress)

            if ($AdapterMac -eq $TargetMac) {

                Write-CrucibleLog (
                    "{0} adapter found: {1} (ifIndex {2})" -f `
                    $Description, `
                    $Adapter.Name, `
                    $Adapter.ifIndex
                )

                return $Adapter
            }
        }

        Write-CrucibleLog (
            "Waiting for {0} adapter by MAC " +
            "(attempt {1}/{2})." -f `
            $Description, `
            $Attempt, `
            $Attempts
        )

        Start-Sleep -Seconds 2
    }

    throw (
        "Could not locate {0} adapter with MAC {1}" -f `
        $Description, `
        $MacAddress
    )
}

function Register-CrucibleBootstrapResumeTask {

    Write-CrucibleLog (
        "Registering bootstrap resume task."
    )

    $PowerShellPath = (
        "$env:SystemRoot\" +
        "System32\WindowsPowerShell\" +
        "v1.0\powershell.exe"
    )

    $ActionArguments = (
        '-NoProfile ' +
        '-ExecutionPolicy Bypass ' +
        '-File "' +
        $PersistentBootstrapPath +
        '"'
    )

    $Action = New-ScheduledTaskAction `
        -Execute $PowerShellPath `
        -Argument $ActionArguments

    $Trigger = New-ScheduledTaskTrigger `
        -AtStartup

    $Principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $BootstrapResumeTaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Force |
        Out-Null
}


function Remove-CrucibleBootstrapResumeTask {

    $ExistingTask = Get-ScheduledTask `
        -TaskName $BootstrapResumeTaskName `
        -ErrorAction SilentlyContinue

    if ($null -eq $ExistingTask) {
        return
    }

    Write-CrucibleLog (
        "Removing bootstrap resume task."
    )

    Unregister-ScheduledTask `
        -TaskName $BootstrapResumeTaskName `
        -Confirm:$false
}

function Invoke-CrucibleWindowsUpdatePass {

    Write-CrucibleLog (
        "Starting Windows Update discovery."
    )


    # ---------------------------------------------------------
    # Ensure core Windows Update services can operate
    # ---------------------------------------------------------

    foreach ($ServiceName in @(
        "wuauserv",
        "bits"
    )) {

        $Service = Get-Service `
            -Name $ServiceName `
            -ErrorAction SilentlyContinue

        if ($null -eq $Service) {
            continue
        }

        if ($Service.Status -ne "Running") {

            Write-CrucibleLog (
                "Starting Windows Update service: {0}" -f `
                $ServiceName
            )

            Start-Service `
                -Name $ServiceName `
                -ErrorAction Stop
        }
    }


    # ---------------------------------------------------------
    # Open native Windows Update Agent session
    # ---------------------------------------------------------

    $UpdateSession = New-Object `
        -ComObject Microsoft.Update.Session

    $UpdateSession.ClientApplicationID = (
        "Operation Crucible"
    )

    $UpdateSearcher = (
        $UpdateSession.CreateUpdateSearcher()
    )


    # ---------------------------------------------------------
    # Find applicable software updates
    #
    # Drivers are deliberately excluded.
    # Hidden updates are deliberately excluded.
    # ---------------------------------------------------------

    $SearchCriteria = (
        "IsInstalled=0 " +
        "and IsHidden=0 " +
        "and Type='Software'"
    )

    Write-CrucibleLog (
        "Searching Windows Update using criteria: {0}" -f `
        $SearchCriteria
    )

    $SearchResult = (
        $UpdateSearcher.Search(
            $SearchCriteria
        )
    )

    $AvailableCount = (
        $SearchResult.Updates.Count
    )

    Write-CrucibleLog (
        "Windows Update found {0} applicable update(s)." -f `
        $AvailableCount
    )

    if ($AvailableCount -eq 0) {

        return @{
            UpdatesInstalled = 0
            RebootRequired = $false
        }
    }


    # ---------------------------------------------------------
    # Build update collection
    # ---------------------------------------------------------

    $UpdatesToInstall = New-Object `
        -ComObject Microsoft.Update.UpdateColl

    for (
        $Index = 0;
        $Index -lt $AvailableCount;
        $Index++
    ) {

        $Update = (
            $SearchResult.Updates.Item(
                $Index
            )
        )

        Write-CrucibleLog (
            "Applicable update: {0}" -f `
            $Update.Title
        )

        if (-not $Update.EulaAccepted) {

            Write-CrucibleLog (
                "Accepting update EULA: {0}" -f `
                $Update.Title
            )

            $Update.AcceptEula()
        }

        if (
            $Update.InstallationBehavior.CanRequestUserInput
        ) {

            throw (
                "Windows Update requires interactive " +
                "input and cannot be installed by the " +
                "Crucible bootstrap: {0}" -f `
                $Update.Title
            )
        }

        [void]$UpdatesToInstall.Add(
            $Update
        )
    }


    # ---------------------------------------------------------
    # Download
    # ---------------------------------------------------------

    Write-CrucibleLog (
        "Downloading Windows updates."
    )

    $Downloader = (
        $UpdateSession.CreateUpdateDownloader()
    )

    $Downloader.Updates = (
        $UpdatesToInstall
    )

    $DownloadResult = (
        $Downloader.Download()
    )

    # Windows Update OperationResultCode:
    #
    #   2 = Succeeded
    #   3 = SucceededWithErrors
    #   4 = Failed
    #   5 = Aborted

    if (
        $DownloadResult.ResultCode -ne 2 -and
        $DownloadResult.ResultCode -ne 3
    ) {

        throw (
            "Windows Update download failed. " +
            "ResultCode={0}" -f `
            $DownloadResult.ResultCode
        )
    }


    # ---------------------------------------------------------
    # Verify all chosen updates were downloaded
    # ---------------------------------------------------------

    for (
        $Index = 0;
        $Index -lt $UpdatesToInstall.Count;
        $Index++
    ) {

        $Update = (
            $UpdatesToInstall.Item(
                $Index
            )
        )

        if (-not $Update.IsDownloaded) {

            throw (
                "Windows update did not finish " +
                "downloading: {0}" -f `
                $Update.Title
            )
        }
    }


    # ---------------------------------------------------------
    # Install
    # ---------------------------------------------------------

    Write-CrucibleLog (
        "Installing Windows updates."
    )

    $Installer = (
        $UpdateSession.CreateUpdateInstaller()
    )

    $Installer.AllowSourcePrompts = $false

    $Installer.Updates = (
        $UpdatesToInstall
    )

    if (
        $Installer.RebootRequiredBeforeInstallation
    ) {

        Write-CrucibleLog (
            "Windows requires a reboot before " +
            "additional updates may be installed."
        )

        return @{
            UpdatesInstalled = 0
            RebootRequired = $true
        }
    }

    $InstallationResult = (
        $Installer.Install()
    )

    Write-CrucibleLog (
        "Windows Update installation result: {0}" -f `
        $InstallationResult.ResultCode
    )


    # ---------------------------------------------------------
    # Check each update individually
    # ---------------------------------------------------------

    for (
        $Index = 0;
        $Index -lt $UpdatesToInstall.Count;
        $Index++
    ) {

        $Update = (
            $UpdatesToInstall.Item(
                $Index
            )
        )

        $UpdateResult = (
            $InstallationResult.GetUpdateResult(
                $Index
            )
        )

        Write-CrucibleLog (
            "Update result [{0}]: ResultCode={1}, " +
            "HResult=0x{2:X8}" -f `
            $Update.Title, `
            $UpdateResult.ResultCode, `
            ([uint32]$UpdateResult.HResult)
        )

        if (
            $UpdateResult.ResultCode -eq 4 -or
            $UpdateResult.ResultCode -eq 5
        ) {

            throw (
                "Windows update failed: {0}" -f `
                $Update.Title
            )
        }
    }


    if (
        $InstallationResult.ResultCode -eq 4 -or
        $InstallationResult.ResultCode -eq 5
    ) {

        throw (
            "Windows Update installation failed. " +
            "ResultCode={0}" -f `
            $InstallationResult.ResultCode
        )
    }


    return @{
        UpdatesInstalled = (
            $UpdatesToInstall.Count
        )

        RebootRequired = (
            [bool]$InstallationResult.RebootRequired
        )
    }
}

function Invoke-CrucibleWindowsUpdates {

    param(
        [int] $MaxPasses = 6
    )

    for (
        $Pass = 1;
        $Pass -le $MaxPasses;
        $Pass++
    ) {

        Write-CrucibleLog (
            "Windows Update pass {0}/{1}." -f `
            $Pass, `
            $MaxPasses
        )

        $Result = (
            Invoke-CrucibleWindowsUpdatePass
        )

        if ($Result.RebootRequired) {

            return @{
                FullyUpdated = $false
                RebootRequired = $true
            }
        }

        if ($Result.UpdatesInstalled -eq 0) {

            Write-CrucibleLog (
                "No additional Windows software " +
                "updates are applicable."
            )

            return @{
                FullyUpdated = $true
                RebootRequired = $false
            }
        }

        Write-CrucibleLog (
            "Update pass installed {0} update(s); " +
            "searching again." -f `
            $Result.UpdatesInstalled
        )
    }

    throw (
        "Windows Update did not converge after " +
        "$MaxPasses passes."
    )
}

try {

    # ---------------------------------------------------------
    # Initialize Crucible state and logging
    # ---------------------------------------------------------

    New-Item `
        -ItemType Directory `
        -Path $StateRoot `
        -Force |
        Out-Null

    # ---------------------------------------------------------
    # Persist bootstrap locally
    #
    # The initial execution comes from CRUCIBLE_WIN media.
    # Windows Update may require one or more reboots, so the
    # bootstrap must be able to resume entirely from C:.
    # ---------------------------------------------------------

    $CurrentScriptPath = (
        [System.IO.Path]::GetFullPath(
            $PSCommandPath
        )
    )

    $PersistentScriptFullPath = (
        [System.IO.Path]::GetFullPath(
            $PersistentBootstrapPath
        )
    )

    if (
        -not $CurrentScriptPath.Equals(
            $PersistentScriptFullPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {

        Copy-Item `
            -LiteralPath $PSCommandPath `
            -Destination $PersistentBootstrapPath `
            -Force

        Write-CrucibleLog (
            "Windows bootstrap persisted to {0}." -f `
            $PersistentBootstrapPath
        )
    }

    Remove-Item `
        -Path $CompletePath `
        -Force `
        -ErrorAction SilentlyContinue

    Remove-Item `
        -Path $FailurePath `
        -Force `
        -ErrorAction SilentlyContinue

    Start-Transcript `
        -Path $LogPath `
        -Append |
        Out-Null

    $TranscriptStarted = $true

    Write-CrucibleLog "Starting Windows bootstrap."


    # ---------------------------------------------------------
    # Verify administrator context
    # ---------------------------------------------------------

    $CurrentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()

    $CurrentPrincipal = New-Object `
        Security.Principal.WindowsPrincipal($CurrentIdentity)

    $AdministratorRole = [Security.Principal.WindowsBuiltInRole]::Administrator

    if (-not $CurrentPrincipal.IsInRole($AdministratorRole)) {
        throw "Crucible Windows bootstrap requires an elevated administrator context."
    }

    Write-CrucibleLog "Administrator context confirmed."


    # ---------------------------------------------------------
    # Persist and load machine-specific Crucible configuration
    # ---------------------------------------------------------

    $SourceConfigPath = Join-Path `
        -Path $PSScriptRoot `
        -ChildPath "crucible-bootstrap.json"

    if (
        Test-Path `
            -LiteralPath $SourceConfigPath
    ) {

        $SourceConfigFullPath = (
            [System.IO.Path]::GetFullPath(
                $SourceConfigPath
            )
        )

        $PersistentConfigFullPath = (
            [System.IO.Path]::GetFullPath(
                $PersistentConfigPath
            )
        )

        if (
            -not $SourceConfigFullPath.Equals(
                $PersistentConfigFullPath,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        ) {

            Copy-Item `
                -LiteralPath $SourceConfigPath `
                -Destination $PersistentConfigPath `
                -Force

            Write-CrucibleLog (
                "Bootstrap configuration persisted to {0}." -f `
                $PersistentConfigPath
            )
        }
    }

    if (
        -not (
            Test-Path `
                -LiteralPath $PersistentConfigPath
        )
    ) {

        throw (
            "Persistent bootstrap configuration " +
            "not found: $PersistentConfigPath"
        )
    }

    Write-CrucibleLog (
        "Loading bootstrap configuration from {0}." -f `
        $PersistentConfigPath
    )

    $ConfigText = Get-Content `
        -LiteralPath $PersistentConfigPath `
        -Raw

    $Config = (
        $ConfigText |
        ConvertFrom-Json
    )

    Write-CrucibleLog (
        "Bootstrap configuration loaded."
    )


    # ---------------------------------------------------------
    # Resolve management settings
    # ---------------------------------------------------------

    $ManagementIp = [string]$Config.management.address
    $PrefixLength = [int]$Config.management.prefix_length
    $InternetMac = [string]$Config.internet.mac_address
    $InternetRouteMetric = [int]$Config.routing.internet_metric
    $TopologyRouteMetric = [int]$Config.routing.topology_metric

    $TopologyInterfaces = @(
        $Config.topology
    )
    $ManagementNetwork = [string]$Config.management.network
    $TargetMac = Normalize-MacAddress ([string]$Config.management.mac_address)
    $WinRmPort = [int]$Config.winrm.port

    Write-CrucibleLog (
        "Management target: {0}/{1}" -f `
        $ManagementIp, `
        $PrefixLength
    )

    Write-CrucibleLog (
        "Management MAC: {0}" -f $TargetMac
    )

    Write-CrucibleLog (
        "WinRM HTTPS port: {0}" -f $WinRmPort
    )


    # ---------------------------------------------------------
    # Locate management NIC by deterministic MAC
    # ---------------------------------------------------------

    $ManagementAdapter = $null

    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {

        $Adapters = Get-NetAdapter `
            -ErrorAction SilentlyContinue

        foreach ($Adapter in $Adapters) {

            $AdapterMac = Normalize-MacAddress ([string]$Adapter.MacAddress)

            if ($AdapterMac -eq $TargetMac) {
                $ManagementAdapter = $Adapter
                break
            }
        }

        if ($null -ne $ManagementAdapter) {
            break
        }

        Write-CrucibleLog (
            "Waiting for management NIC (attempt {0}/30)." -f $Attempt
        )

        Start-Sleep -Seconds 2
    }

    if ($null -eq $ManagementAdapter) {
        throw "Could not locate Crucible management NIC with MAC $TargetMac"
    }

    $InterfaceIndex = [int]$ManagementAdapter.ifIndex

    Write-CrucibleLog (
        "Management NIC found: {0} (ifIndex {1})" -f `
        $ManagementAdapter.Name, `
        $InterfaceIndex
    )


    # ---------------------------------------------------------
    # Enable adapter if required
    # ---------------------------------------------------------

    if ($ManagementAdapter.Status -eq "Disabled") {

        Write-CrucibleLog "Enabling management NIC."

        Enable-NetAdapter `
            -InterfaceIndex $InterfaceIndex `
            -Confirm:$false

        Start-Sleep -Seconds 2
    }

    # ---------------------------------------------------------
    # Configure static management IPv4 address
    # ---------------------------------------------------------

    Write-CrucibleLog "Configuring management IPv4 address."

    Set-NetIPInterface `
        -InterfaceIndex $InterfaceIndex `
        -AddressFamily IPv4 `
        -Dhcp Disabled

    $ExistingAddresses = @(
        Get-NetIPAddress `
            -InterfaceIndex $InterfaceIndex `
            -AddressFamily IPv4 `
            -ErrorAction SilentlyContinue
    )

    foreach ($Address in $ExistingAddresses) {

        if ($Address.IPAddress -ne $ManagementIp) {

            Write-CrucibleLog (
                "Removing existing management NIC address: {0}" -f `
                $Address.IPAddress
            )

            Remove-NetIPAddress `
                -InterfaceIndex $InterfaceIndex `
                -IPAddress $Address.IPAddress `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        }
    }


    # The Crucible management interface must never become
    # Windows' default Internet route. The appended Crucible
    # NAT interface owns Internet routing when present.
    $DefaultRoutes = @(
        Get-NetRoute `
            -InterfaceIndex $InterfaceIndex `
            -AddressFamily IPv4 `
            -DestinationPrefix "0.0.0.0/0" `
            -ErrorAction SilentlyContinue
    )

    foreach ($Route in $DefaultRoutes) {

        Remove-NetRoute `
            -InterfaceIndex $InterfaceIndex `
            -DestinationPrefix "0.0.0.0/0" `
            -Confirm:$false `
            -ErrorAction SilentlyContinue
    }


    $ExistingManagementAddress = Get-NetIPAddress `
        -InterfaceIndex $InterfaceIndex `
        -AddressFamily IPv4 `
        -IPAddress $ManagementIp `
        -ErrorAction SilentlyContinue

    if ($null -eq $ExistingManagementAddress) {

        New-NetIPAddress `
            -InterfaceIndex $InterfaceIndex `
            -IPAddress $ManagementIp `
            -PrefixLength $PrefixLength |
            Out-Null
    }

    Set-DnsClientServerAddress `
        -InterfaceIndex $InterfaceIndex `
        -ResetServerAddresses `
        -ErrorAction SilentlyContinue

    Write-CrucibleLog "Management IPv4 configuration complete."


    # ---------------------------------------------------------
    # Mark management network as Private
    # ---------------------------------------------------------

    for ($Attempt = 1; $Attempt -le 15; $Attempt++) {

        $ConnectionProfile = Get-NetConnectionProfile `
            -InterfaceIndex $InterfaceIndex `
            -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($null -ne $ConnectionProfile) {

            Set-NetConnectionProfile `
                -InterfaceIndex $InterfaceIndex `
                -NetworkCategory Private

            Write-CrucibleLog "Management network marked Private."

            break
        }

        Start-Sleep -Seconds 1
    }

    # ---------------------------------------------------------
    # Permit remote administration using local Crucible admin
    # ---------------------------------------------------------

    $TokenFilterPath = (
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
    )

    $TokenFilterParams = @{
        Path = $TokenFilterPath
        Name = "LocalAccountTokenFilterPolicy"
        Value = 1
        PropertyType = "DWORD"
        Force = $true
    }

    New-ItemProperty @TokenFilterParams |
        Out-Null

    Write-CrucibleLog "Local administrator remote token policy configured."


    # ---------------------------------------------------------
    # Enable PowerShell remoting / WinRM
    # ---------------------------------------------------------

    Write-CrucibleLog "Enabling PowerShell remoting."

    Enable-PSRemoting `
        -Force `
        -SkipNetworkProfileCheck

    Set-Service `
        -Name WinRM `
        -StartupType Automatic

    Write-CrucibleLog "WinRM service enabled."


    # ---------------------------------------------------------
    # Create or locate TLS certificate
    # ---------------------------------------------------------

    $Certificate = $null

    $Certificates = Get-ChildItem `
        -Path "Cert:\LocalMachine\My" `
        -ErrorAction SilentlyContinue

    foreach ($Candidate in $Certificates) {

        if (
            $Candidate.Subject -eq "CN=$env:COMPUTERNAME" -and
            $Candidate.NotAfter -gt (Get-Date)
        ) {
            $Certificate = $Candidate
            break
        }
    }

    if ($null -eq $Certificate) {

        Write-CrucibleLog "Creating WinRM TLS certificate."

        $CertificateParams = @{
            DnsName = $env:COMPUTERNAME
            Subject = "CN=$env:COMPUTERNAME"
            CertStoreLocation = "Cert:\LocalMachine\My"
            Type = "SSLServerAuthentication"
            NotAfter = (Get-Date).AddYears(2)
        }

        $Certificate = New-SelfSignedCertificate @CertificateParams
    }

    if ($null -eq $Certificate) {
        throw "Failed to create or locate the WinRM TLS certificate."
    }

    Write-CrucibleLog (
        "Using TLS certificate: {0}" -f $Certificate.Thumbprint
    )


    # ---------------------------------------------------------
    # Replace existing HTTPS WinRM listeners
    # ---------------------------------------------------------

    $ExistingHttpsListeners = @(
        Get-ChildItem `
            -Path "WSMan:\localhost\Listener" `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Keys -contains "Transport=HTTPS"
            }
    )

    foreach ($Listener in $ExistingHttpsListeners) {

        Write-CrucibleLog "Removing existing WinRM HTTPS listener."

        Remove-Item `
            -Path $Listener.PSPath `
            -Recurse `
            -Force
    }


    Write-CrucibleLog (
        "Creating WinRM HTTPS listener on port {0}." -f $WinRmPort
    )

    New-Item `
        -Path "WSMan:\localhost\Listener" `
        -Address "*" `
        -Transport HTTPS `
        -CertificateThumbprint $Certificate.Thumbprint `
        -Port $WinRmPort `
        -Force |
        Out-Null

    # The WSMan provider supports creation of listeners with
    # Transport, CertificateThumbprint and Port parameters.


    # ---------------------------------------------------------
    # Restrict WinRM HTTPS firewall access to mgmt network
    # ---------------------------------------------------------

    $FirewallRuleName = "Crucible-WinRM-HTTPS"

    $ExistingFirewallRule = Get-NetFirewallRule `
        -Name $FirewallRuleName `
        -ErrorAction SilentlyContinue

    if ($null -ne $ExistingFirewallRule) {

        Remove-NetFirewallRule `
            -Name $FirewallRuleName
    }

    $FirewallParams = @{
        Name = $FirewallRuleName
        DisplayName = "Operation Crucible WinRM HTTPS"
        Description = "Allow WinRM HTTPS from the Crucible management network."
        Direction = "Inbound"
        Action = "Allow"
        Protocol = "TCP"
        LocalPort = $WinRmPort
        RemoteAddress = $ManagementNetwork
        Profile = "Any"
    }

    New-NetFirewallRule @FirewallParams |
        Out-Null

    Write-CrucibleLog "WinRM HTTPS firewall rule configured."


    # ---------------------------------------------------------
    # Restart WinRM and wait for the HTTPS socket
    # ---------------------------------------------------------

    Restart-Service `
        -Name WinRM `
        -Force

    $WinRmReady = $false

    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {

        $ListenerSocket = Get-NetTCPConnection `
            -State Listen `
            -LocalPort $WinRmPort `
            -ErrorAction SilentlyContinue |
            Select-Object -First 1

        if ($null -ne $ListenerSocket) {

            $WinRmReady = $true
            break
        }

        Write-CrucibleLog (
            "Waiting for WinRM HTTPS (attempt {0}/30)." -f $Attempt
        )

        Start-Sleep -Seconds 1
    }

    if (-not $WinRmReady) {
        throw "WinRM did not begin listening on port $WinRmPort"
    }

    Write-CrucibleLog (
        "WinRM HTTPS is listening on port {0}." -f $WinRmPort
    )

    # ---------------------------------------------------------
    # Prefer Crucible temporary NAT while it exists
    # ---------------------------------------------------------

    $InternetAdapter = Find-CrucibleNetAdapterByMac `
        -MacAddress $InternetMac `
        -Description "Crucible Internet"

    $InternetInterfaceIndex = [int]$InternetAdapter.ifIndex

    Set-NetIPInterface `
        -InterfaceIndex $InternetInterfaceIndex `
        -AddressFamily IPv4 `
        -AutomaticMetric Disabled `
        -InterfaceMetric $InternetRouteMetric

    Write-CrucibleLog (
        "Crucible Internet interface metric set to {0}." -f `
        $InternetRouteMetric
    )

    # ---------------------------------------------------------
    # Configure persistent topology interfaces
    # ---------------------------------------------------------

    foreach ($InterfaceSpec in $TopologyInterfaces) {

        $Label = [string]$InterfaceSpec.label
        $MacAddress = [string]$InterfaceSpec.mac_address

        $TopologyAdapter = Find-CrucibleNetAdapterByMac `
            -MacAddress $MacAddress `
            -Description ("topology interface '{0}'" -f $Label)

        $TopologyIndex = [int]$TopologyAdapter.ifIndex

        if ($TopologyAdapter.Status -eq "Disabled") {

            Enable-NetAdapter `
                -InterfaceIndex $TopologyIndex `
                -Confirm:$false

            Start-Sleep -Seconds 1
        }

        Set-NetIPInterface `
            -InterfaceIndex $TopologyIndex `
            -AddressFamily IPv4 `
            -AutomaticMetric Disabled `
            -InterfaceMetric $TopologyRouteMetric

        $Method = [string]$InterfaceSpec.ipv4.method

        if ($Method -eq "dhcp") {

            Write-CrucibleLog (
                "Configuring topology interface '{0}' for DHCP." -f `
                $Label
            )

            Set-NetIPInterface `
                -InterfaceIndex $TopologyIndex `
                -AddressFamily IPv4 `
                -Dhcp Enabled `
                -AutomaticMetric Disabled `
                -InterfaceMetric $TopologyRouteMetric

            Set-DnsClientServerAddress `
                -InterfaceIndex $TopologyIndex `
                -ResetServerAddresses `
                -ErrorAction SilentlyContinue

            continue
        }

        if ($Method -ne "static") {

            throw (
                "Unsupported IPv4 method '{0}' " +
                "for topology interface '{1}'." -f `
                $Method, `
                $Label
            )
        }

        Write-CrucibleLog (
            "Configuring topology interface '{0}' statically." -f `
            $Label
        )

        Set-NetIPInterface `
            -InterfaceIndex $TopologyIndex `
            -AddressFamily IPv4 `
            -Dhcp Disabled `
            -AutomaticMetric Disabled `
            -InterfaceMetric $TopologyRouteMetric

        $ExistingAddresses = @(
            Get-NetIPAddress `
                -InterfaceIndex $TopologyIndex `
                -AddressFamily IPv4 `
                -ErrorAction SilentlyContinue
        )

        foreach ($Address in $ExistingAddresses) {

            Remove-NetIPAddress `
                -InterfaceIndex $TopologyIndex `
                -IPAddress $Address.IPAddress `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        }

        $ExistingDefaultRoutes = @(
            Get-NetRoute `
                -InterfaceIndex $TopologyIndex `
                -AddressFamily IPv4 `
                -DestinationPrefix "0.0.0.0/0" `
                -ErrorAction SilentlyContinue
        )

        foreach ($Route in $ExistingDefaultRoutes) {

            Remove-NetRoute `
                -InterfaceIndex $TopologyIndex `
                -DestinationPrefix "0.0.0.0/0" `
                -Confirm:$false `
                -ErrorAction SilentlyContinue
        }

        $AddressText = [string]$InterfaceSpec.ipv4.address
        $AddressParts = $AddressText.Split("/")

        if ($AddressParts.Count -ne 2) {

            throw (
                "Invalid CIDR address '{0}' for topology " +
                "interface '{1}'." -f `
                $AddressText, `
                $Label
            )
        }

        $IpAddress = [string]$AddressParts[0]
        $StaticPrefixLength = [int]$AddressParts[1]

        $Gateway = [string]$InterfaceSpec.ipv4.gateway

        $NewAddressParams = @{
            InterfaceIndex = $TopologyIndex
            IPAddress = $IpAddress
            PrefixLength = $StaticPrefixLength
        }

        if (-not [string]::IsNullOrWhiteSpace($Gateway)) {

            $NewAddressParams["DefaultGateway"] = $Gateway
        }

        New-NetIPAddress @NewAddressParams |
            Out-Null

        Set-DnsClientServerAddress `
            -InterfaceIndex $TopologyIndex `
            -ResetServerAddresses `
            -ErrorAction SilentlyContinue

        Write-CrucibleLog (
            "Topology interface '{0}' configured as {1}." -f `
            $Label, `
            $AddressText
        )
    }

    Write-CrucibleLog "Persistent topology interface configuration complete."

    # ---------------------------------------------------------
    # Fully update Windows
    #
    # Operation Crucible requires Internet connectivity.
    #
    # Windows Update is part of bootstrap completion.
    # A machine is not considered bootstrap-complete until:
    #
    #   - all currently applicable software updates have
    #     been installed;
    #   - any update-required reboot has occurred;
    #   - a subsequent Windows Update search finds no
    #     additional applicable software updates.
    # ---------------------------------------------------------

    if (
        -not (
            Test-Path `
                -LiteralPath $WindowsUpdateCompletePath
        )
    ) {

        Write-CrucibleLog (
            "Beginning Crucible Windows Update stage."
        )

        $WindowsUpdateResult = (
            Invoke-CrucibleWindowsUpdates
        )

        if (
            $WindowsUpdateResult.RebootRequired
        ) {

            $UpdateCycle = 0

            if (
                Test-Path `
                    -LiteralPath $WindowsUpdateCyclePath
            ) {

                $RawCycle = Get-Content `
                    -LiteralPath $WindowsUpdateCyclePath `
                    -Raw

                $ParsedCycle = 0

                if (
                    [int]::TryParse(
                        $RawCycle.Trim(),
                        [ref]$ParsedCycle
                    )
                ) {

                    $UpdateCycle = (
                        $ParsedCycle
                    )
                }
            }

            $UpdateCycle++

            if (
                $UpdateCycle -gt
                $MaxWindowsUpdateReboots
            ) {

                throw (
                    "Windows Update exceeded the " +
                    "maximum of {0} bootstrap reboot(s)." -f `
                    $MaxWindowsUpdateReboots
                )
            }

            Set-Content `
                -LiteralPath $WindowsUpdateCyclePath `
                -Value $UpdateCycle `
                -Encoding ASCII

            Write-CrucibleLog (
                "Windows Update requires reboot {0}/{1}." -f `
                $UpdateCycle, `
                $MaxWindowsUpdateReboots
            )

            Register-CrucibleBootstrapResumeTask

            Write-CrucibleLog (
                "Restarting Windows to continue bootstrap."
            )

            if ($TranscriptStarted) {

                Stop-Transcript |
                    Out-Null

                $TranscriptStarted = $false
            }

            Restart-Computer `
                -Force

            exit 0
        }


        if (
            -not $WindowsUpdateResult.FullyUpdated
        ) {

            throw (
                "Windows Update stage returned without " +
                "rebooting but did not report completion."
            )
        }


        Set-Content `
            -LiteralPath $WindowsUpdateCompletePath `
            -Value (Get-Date).ToString("o") `
            -Encoding ASCII

        Write-CrucibleLog (
            "Windows Update stage complete."
        )
    }


    # ---------------------------------------------------------
    # Clean up reboot-resume state
    # ---------------------------------------------------------

    Remove-CrucibleBootstrapResumeTask

    Remove-Item `
        -LiteralPath $WindowsUpdateCyclePath `
        -Force `
        -ErrorAction SilentlyContinue

    # ---------------------------------------------------------
    # Signal successful bootstrap completion
    # ---------------------------------------------------------

    Set-Content `
        -Path $CompletePath `
        -Value (Get-Date).ToString("o") `
        -Encoding ASCII

    Write-CrucibleLog "Windows bootstrap completed successfully."

}
catch {

    $BootstrapExitCode = 1

    $FailureMessage = ($_ | Out-String)

    try {

        if (-not (Test-Path -LiteralPath $StateRoot)) {

            New-Item `
                -ItemType Directory `
                -Path $StateRoot `
                -Force |
                Out-Null
        }

        Set-Content `
            -Path $FailurePath `
            -Value $FailureMessage `
            -Encoding UTF8
    }
    catch {
        # Do not hide the original bootstrap failure if
        # writing the failure marker itself fails.
    }

    [Console]::Error.WriteLine(
        "Operation Crucible Windows bootstrap failed."
    )

    [Console]::Error.WriteLine(
        $FailureMessage
    )
}
finally {

    if ($TranscriptStarted) {

        try {
            Stop-Transcript |
                Out-Null
        }
        catch {
            # Ignore transcript shutdown errors.
        }
    }
}


exit $BootstrapExitCode
