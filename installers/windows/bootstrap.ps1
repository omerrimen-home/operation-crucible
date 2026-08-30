#requires -version 5.1

Set-StrictMode -Version Latest

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$StateRoot = Join-Path -Path $env:ProgramData -ChildPath "Crucible"
$LogPath = Join-Path -Path $StateRoot -ChildPath "bootstrap.log"
$CompletePath = Join-Path -Path $StateRoot -ChildPath "bootstrap-complete"
$FailurePath = Join-Path -Path $StateRoot -ChildPath "bootstrap-failed"

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

try {

    # ---------------------------------------------------------
    # Initialize Crucible state and logging
    # ---------------------------------------------------------

    New-Item `
        -ItemType Directory `
        -Path $StateRoot `
        -Force |
        Out-Null

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
    # Read machine-specific Crucible configuration
    # ---------------------------------------------------------

    $ConfigPath = Join-Path `
        -Path $PSScriptRoot `
        -ChildPath "crucible-bootstrap.json"

    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        throw "Bootstrap configuration not found: $ConfigPath"
    }

    Write-CrucibleLog "Loading bootstrap configuration from $ConfigPath."

    $ConfigText = Get-Content `
        -LiteralPath $ConfigPath `
        -Raw

    $Config = $ConfigText | ConvertFrom-Json

    $StoredConfigPath = Join-Path `
        -Path $StateRoot `
        -ChildPath "bootstrap-config.json"

    Copy-Item `
        -LiteralPath $ConfigPath `
        -Destination $StoredConfigPath `
        -Force

    Write-CrucibleLog "Bootstrap configuration loaded."


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
