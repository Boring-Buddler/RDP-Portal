[CmdletBinding()]
param(
    [string]$ExpectedComputerName = 'Remote-Ettlingen',
    [string]$StatusDirectory = 'C:\RDP-Portal-Daten\agenten-status',
    [string]$ShareName = 'RDP-Status',
    [string]$ReaderName = 'PortalLeser',
    [string[]]$AllowedRemoteAddress = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Initialize-StatusShare {
    param(
        [string]$Directory, [string]$Name, [string]$Reader,
        [Security.SecureString]$Password
    )
    # Refuse existing objects: no password resets, ACL replacement or overwriting
    # an existing share on a repeatedly executed setup.
    if (Get-LocalUser -Name $Reader -ErrorAction SilentlyContinue) {
        throw "Das Konto $Reader besteht bereits. Keine Änderung vorgenommen."
    }
    if (Get-SmbShare -Name $Name -ErrorAction SilentlyContinue) {
        throw "Die Freigabe $Name besteht bereits. Keine Änderung vorgenommen."
    }
    if (Test-Path -LiteralPath $Directory) {
        throw "Der Statusordner besteht bereits. Zum Schutz bestehender Daten keine Änderung vorgenommen: $Directory"
    }
    $parent = Split-Path -Parent $Directory
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $createdUser = $null
    $createdShare = $false
    $createdDirectory = $false
    try {
        $createdUser = New-LocalUser -Name $Reader -Password $Password -Description 'Lesekonto fuer RDP-Agent-Status'
        New-Item -ItemType Directory -Path $Directory -ErrorAction Stop | Out-Null
        $createdDirectory = $true
        $acl = New-Object System.Security.AccessControl.DirectorySecurity
        $acl.SetAccessRuleProtection($true, $false)
        $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
        $propagation = [Security.AccessControl.PropagationFlags]::None
        $allow = [Security.AccessControl.AccessControlType]::Allow
        foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
            $identity = [Security.Principal.SecurityIdentifier]::new($sid)
            $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', $inherit, $propagation, $allow))
        }
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($createdUser.SID, 'ReadAndExecute', $inherit, $propagation, $allow))
        Set-Acl -LiteralPath $Directory -AclObject $acl
        $readerAccount = "$env:COMPUTERNAME\$Reader"
        $admins = ([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')).Translate([Security.Principal.NTAccount]).Value
        New-SmbShare -Name $Name -Path $Directory -ReadAccess $readerAccount -FullAccess $admins -CachingMode None -FolderEnumerationMode AccessBased | Out-Null
        $createdShare = $true
        return $readerAccount
    } catch {
        # Roll back only objects created by this invocation. Never remove files.
        if ($createdShare) { Remove-SmbShare -Name $Name -Force }
        if ($createdUser) { Remove-LocalUser -SID $createdUser.SID }
        if ($createdDirectory -and (Test-Path -LiteralPath $Directory -PathType Container)) {
            if (@(Get-ChildItem -LiteralPath $Directory -Force).Count -eq 0) {
                Remove-Item -LiteralPath $Directory  # empty directory only; no recursion
            }
        }
        throw
    }
}

$actualComputer = [Net.Dns]::GetHostName().Split('.')[0]
if ($actualComputer -ine $ExpectedComputerName -and $env:COMPUTERNAME -ine $ExpectedComputerName) {
    throw "Dieses Skript ist für $ExpectedComputerName vorbereitet. Aktueller Rechner: $actualComputer. Es wurde nichts eingerichtet."
}
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'PowerShell auf dem Freigabe-Rechner als Administrator öffnen und das Skript dort starten.'
}
if ($ReaderName -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,19}$' -or $ShareName -notmatch '^[A-Za-z][A-Za-z0-9_-]{0,79}$') {
    throw 'Ungültiger Konto- oder Freigabename.'
}
if ($StatusDirectory -notmatch '^[A-Za-z]:\\' -or $StatusDirectory -match '[*?]' -or $StatusDirectory.Contains('..')) {
    throw 'Als Statusordner einen vollständigen lokalen Ordnerpfad angeben.'
}
$StatusDirectory = [IO.Path]::GetFullPath($StatusDirectory).TrimEnd('\')
# Do not follow existing directory junctions, symlinks or redirected folders.
$ancestor = $StatusDirectory
while ($ancestor) {
    if (Test-Path -LiteralPath $ancestor) {
        if ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Verknüpfung im Zielpfad; Einrichtung abgebrochen: $ancestor"
        }
    }
    $ancestor = Split-Path -Parent $ancestor
}
foreach ($address in $AllowedRemoteAddress) {
    $parts = $address.Split('/')
    $ip = $null
    if ($parts.Count -gt 2 -or -not [Net.IPAddress]::TryParse($parts[0], [ref]$ip) -or
        $ip.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        ($parts.Count -eq 2 -and ($parts[1] -notmatch '^([1-9]|[12][0-9]|3[0-2])$'))) {
        throw 'Firewall-Adressen müssen IPv4-Adressen oder IPv4-Netze mit Präfix 1 bis 32 sein.'
    }
}
Write-Host "Rechner: $actualComputer"
Write-Host "Neuer Statusordner: $StatusDirectory"
Write-Host "Neues Lesekonto: $env:COMPUTERNAME\$ReaderName"
Write-Host 'Ein eigenes Kennwort für das Lesekonto vergeben und im Passwortmanager aufbewahren.'
$password = Read-Host 'Kennwort (Eingabe verdeckt)' -AsSecureString
if ($password.Length -eq 0) { throw 'Ein leeres Kennwort ist nicht zulässig.' }
try {
    $readerAccount = Initialize-StatusShare -Directory $StatusDirectory -Name $ShareName -Reader $ReaderName -Password $password
} finally { $password.Dispose() }
if ($AllowedRemoteAddress.Count) {
    $ruleName = 'Kirschke-RDP-Status-SMB'
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
        Write-Warning 'Vorhandene Firewall-Regel wurde nicht überschrieben. Deren Geltungsbereich bitte prüfen.'
    } else {
        New-NetFirewallRule -Name $ruleName -DisplayName 'Kirschke RDP Status - SMB' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 445 -RemoteAddress $AllowedRemoteAddress -Profile Any | Out-Null
    }
} else {
    Write-Host 'Firewall unverändert. TCP 445 muss von den Portal-PCs über LAN/VPN erreichbar sein.'
}
Write-Host "Agent-Setup auf diesem Rechner: $StatusDirectory"
Write-Host "Portal-Konfigurator: \\$actualComputer\$ShareName"
Write-Host "Freigabebenutzer: $readerAccount"
Write-Host 'Einrichtung abgeschlossen. Der Agent muss nun auf den lokalen Statusordner eingestellt werden.'
