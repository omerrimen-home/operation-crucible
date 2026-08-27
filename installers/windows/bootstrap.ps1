#requires -version 5.1

Set-StrictMode -Version Latest

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"


$StateRoot = Join-Path `
    $env:ProgramData `
    "Crucible"

New-Item `
    -ItemType Directory `
    -Path $StateRoot `
    -Force `
    | Out-Null


$LogPath = Join-Path `
    $StateRoot `
    "bootstrap.log"

Start-Transcript `
    -Path $LogPath `
    -Append `
    | Out-Null


function Write-CrucibleLog {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Message
    )

    $timestamp = (
        Get-Date
    ).ToString("o")

    Write-Host (
        "[{0}] {1}" -f
        $timestamp,
        $Message
    )
}


try {

    Write-CrucibleLog `
        "Starting Windows bootstrap."


    # ---------------------------------------------------------
    # Read machine-specific Crucible configuration
    # ---------------------------------------------------------

    $ConfigPath = Join-Path `
        $PSScriptRoot `
        "crucible-bootstrap.json"

    if (-not (
        Test-Path $ConfigPath
    )) {
        throw (
            "Bootstrap configuration not found: "
            + $ConfigPath
        )
    }


    $Config = (
        Get-Content `
            -Path $ConfigPath `
            -Raw
        | ConvertFrom-Json
    )


    Copy-Item `
        -Path $ConfigPath `
        -Destination (
            Join-Path `
                $StateRoot `
                "bootstrap-config.json"
        ) `
        -Force


    # ---------------------------------------------------------
    # Resolve management settings
    # ---------------------------------------------------------

    $ManagementIp = [string] (
        $Config.management.address
    )

    $PrefixLength = [int] (
        $Config.management.prefix_length
    )

    $ManagementNetwork = [string] (
        $Config.management.network
    )

    $TargetMac = (
        [string] (
            $Config.management.mac_address
        )
    ).Replace(
        ":",
        ""
    ).Replace(
        "-",
        ""
    ).ToUpperInvariant()


    $WinRmPort = [int] (
        $Config.winrm.port
    )


    Write-CrucibleLog (
        "Management target: {0}/{1}" -f
        $ManagementIp,
        $PrefixLength
    )

    Write-CrucibleLog (
        "Management MAC: {0}" -f
        $TargetMac
    )


    # ---------------------------------------------------------
    # Locate management NIC by MAC
    # ---------------------------------------------------------

    $ManagementAdapter = $null


    for (
        $Attempt = 1;
        $Attempt -le 30;
        $Attempt++
    ) {

        $ManagementAdapter = (
            Get-NetAdapter `
                -ErrorAction SilentlyContinue
            | Where-Object {

                $AdapterMac = (
                    [string] $_.MacAddress
                ).Replace(
                    ":",
                    ""
                ).Replace(
                    "-",
                    ""
                ).ToUpperInvariant()

                $AdapterMac -eq $TargetMac
            }
            | Select-Object -First 1
        )


        if ($null -ne $ManagementAdapter) {
            break
        }


        Write-CrucibleLog (
            "Waiting for management NIC "
            + "(attempt $Attempt/30)."
        )

        Start-Sleep -Seconds 2
    }


    if ($null -eq $ManagementAdapter) {
        throw (
            "Could not locate Crucible management "
            + "NIC with MAC "
            + $TargetMac
        )
    }


    $InterfaceIndex = (
        $ManagementAdapter.ifIndex
    )


    Write-CrucibleLog (
        "Management NIC found: "
        + $ManagementAdapter.Name
        + " (ifIndex "
        + $InterfaceIndex
        + ")"
    )


    # ---------------------------------------------------------
    # Enable adapter if necessary
    # ---------------------------------------------------------

    if (
        $ManagementAdapter.Status
        -eq "Disabled"
    ) {

        Enable-NetAdapter `
            -InterfaceIndex $InterfaceIndex `
            -Confirm:$false

        Start-Sleep -Seconds 2
    }


    # ---------------------------------------------------------
    # Configure static management IPv4 address
    # ---------------------------------------------------------

    Set-NetIPInterface `
        -InterfaceIndex $InterfaceIndex `
        -AddressFamily IPv4 `
        -Dhcp Disabled


    Get-NetIPAddress `
        -InterfaceIndex $InterfaceIndex `
        -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue `
    | Where-Object {
        $_.IPAddress -ne $ManagementIp
    } `
    | Remove-NetIPAddress `
        -Confirm:$false `
        -ErrorAction SilentlyContinue


    Get-NetRoute `
        -InterfaceIndex $InterfaceIndex `
        -AddressFamily IPv4 `
        -ErrorAction SilentlyContinue `
    | Where-Object {
        $_.DestinationPrefix -eq "0.0.0.0/0"
    } `
    | Remove-NetRoute `
        -Confirm:$false `
        -ErrorAction SilentlyContinue


    $ExistingAddress = (
        Get-NetIPAddress `
            -InterfaceIndex $InterfaceIndex `
            -AddressFamily IPv4 `
            -ErrorAction SilentlyContinue
        | Where-Object {
            $_.IPAddress -eq $ManagementIp
        }
        | Select-Object -First 1
    )


    if ($null -eq $ExistingAddress) {

        New-NetIPAddress `
            -InterfaceIndex $InterfaceIndex `
            -IPAddress $ManagementIp `
            -PrefixLength $PrefixLength `
            | Out-Null
    }


    Set-DnsClientServerAddress `
        -InterfaceIndex $InterfaceIndex `
        -ResetServerAddresses `
        -ErrorAction SilentlyContinue


    Write-CrucibleLog `
        "Management IPv4 configuration complete."


    # ---------------------------------------------------------
    # Mark management network Private where possible
    # ---------------------------------------------------------

    for (
        $Attempt = 1;
        $Attempt -le 15;
        $Attempt++
    ) {

        $ConnectionProfile = (
            Get-NetConnectionProfile `
                -InterfaceIndex $InterfaceIndex `
                -ErrorAction SilentlyContinue
        )


        if ($null -ne $ConnectionProfile) {

            Set-NetConnectionProfile `
                -InterfaceIndex $InterfaceIndex `
                -NetworkCategory Private

            break
        }


        Start-Sleep -Seconds 1
    }


    # ---------------------------------------------------------
    # Allow local Crucible administrator through remote UAC
    # ---------------------------------------------------------

    $TokenFilterParams = @{

        Path = (
            "HKLM:\SOFTWARE\Microsoft\Windows\"
            + "CurrentVersion\Policies\System"
        )

        Name = (
            "LocalAccountTokenFilterPolicy"
        )

        Value = 1

        PropertyType = "DWORD"

        Force = $true
    }


    New-ItemProperty `
        @TokenFilterParams `
        | Out-Null


    # ---------------------------------------------------------
    # Enable PowerShell remoting / WinRM
    # ---------------------------------------------------------

    Write-CrucibleLog `
        "Enabling PowerShell remoting."


    Enable-PSRemoting `
        -Force `
        -SkipNetworkProfileCheck


    Set-Service `
        -Name WinRM `
        -StartupType Automatic


    # ---------------------------------------------------------
    # Create self-signed TLS certificate
    # ---------------------------------------------------------

    $Certificate = (
        Get-ChildItem `
            "Cert:\LocalMachine\My"
        | Where-Object {

            $_.Subject -eq (
                "CN="
                + $env:COMPUTERNAME
            )

            -and

            $_.NotAfter -gt (
                Get-Date
            )
        }
        | Sort-Object `
            NotAfter `
            -Descending
        | Select-Object -First 1
    )


    if ($null -eq $Certificate) {

        Write-CrucibleLog `
            "Creating WinRM TLS certificate."


        $Certificate = (
            New-SelfSignedCertificate `
                -DnsName $env:COMPUTERNAME `
                -Subject (
                    "CN="
                    + $env:COMPUTERNAME
                ) `
                -CertStoreLocation (
                    "Cert:\LocalMachine\My"
                ) `
                -Type SSLServerAuthentication `
                -NotAfter (
                    Get-Date
                ).AddYears(2)
        )
    }


    # ---------------------------------------------------------
    # Create HTTPS WinRM listener
    # ---------------------------------------------------------

    $ExistingHttpsListeners = @(
        Get-ChildItem `
            "WSMan:\localhost\Listener" `
            -ErrorAction SilentlyContinue
        | Where-Object {
            $_.Keys -contains (
                "Transport=HTTPS"
            )
        }
    )


    foreach (
        $Listener
        in $ExistingHttpsListeners
    ) {

        Remove-Item `
            -Path $Listener.PSPath `
            -Recurse `
            -Force
    }


    $HttpsListenerParams = @{

        Path = (
            "WSMan:\localhost\Listener"
        )

        Address = "*"

        Transport = "HTTPS"

        CertificateThumbprint = (
            $Certificate.Thumbprint
        )

        Enabled = $true

        Port = $WinRmPort

        Force = $true
    }


    New-Item `
        @HttpsListenerParams `
        | Out-Null


    # ---------------------------------------------------------
    # Restrict Crucible WinRM firewall access to mgmt network
    # ---------------------------------------------------------

    $FirewallRuleName = (
        "Crucible-WinRM-HTTPS"
    )


    $ExistingFirewallRule = (
        Get-NetFirewallRule `
            -Name $FirewallRuleName `
            -ErrorAction SilentlyContinue
    )


    if (
        $null -ne $ExistingFirewallRule
    ) {

        Remove-NetFirewallRule `
            -Name $FirewallRuleName
    }


    New-NetFirewallRule `
        -Name $FirewallRuleName `
        -DisplayName (
            "Operation Crucible WinRM HTTPS"
        ) `
        -Description (
            "Allow WinRM HTTPS from the "
            + "Crucible management network."
        ) `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort $WinRmPort `
        -RemoteAddress $ManagementNetwork `
        -Profile Any `
        | Out-Null


    Restart-Service `
        -Name WinRM `
        -Force


    # ---------------------------------------------------------
    # Wait for WinRM HTTPS listener
    # ---------------------------------------------------------

    $WinRmReady = $false


    for (
        $Attempt = 1;
        $Attempt -le 30;
        $Attempt++
    ) {

        $ListenerSocket = (
            Get-NetTCPConnection `
                -State Listen `
                -LocalPort $WinRmPort `
                -ErrorAction SilentlyContinue
        )


        if ($null -ne $ListenerSocket) {

            $WinRmReady = $true

            break
        }


        Write-CrucibleLog (
            "Waiting for WinRM HTTPS "
            + "(attempt $Attempt/30)."
        )

        Start-Sleep -Seconds 1
    }


    if (-not $WinRmReady) {

        throw (
            "WinRM did not begin listening "
            + "on port "
            + $WinRmPort
        )
    }


    Write-CrucibleLog (
        "WinRM HTTPS is listening on port "
        + $WinRmPort
    )


    # ---------------------------------------------------------
    # Signal Crucible completion
    # ---------------------------------------------------------

    $MarkerPath = Join-Path `
        $StateRoot `
        "bootstrap-complete"


    Set-Content `
        -Path $MarkerPath `
        -Value (
            Get-Date
        ).ToString("o") `
        -Encoding ASCII


    Write-CrucibleLog `
        "Windows bootstrap completed successfully."


}
catch {

    $FailurePath = Join-Path `
        $StateRoot `
        "bootstrap-failed"


    $FailureMessage = (
        $_
        | Out-String
    )


    Set-Content `
        -Path $FailurePath `
        -Value $FailureMessage `
        -Encoding UTF8


    Write-Error $_

    exit 1
}
finally {

    try {
        Stop-Transcript |
            Out-Null
    }
    catch {
        # Ignore transcript shutdown errors.
    }
}
