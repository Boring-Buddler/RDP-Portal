<#
.SYNOPSIS
    Prepares Active Directory groups for the Kirschke RDP Portal.

.DESCRIPTION
    Run in an elevated PowerShell on an AD management workstation. Nothing is
    installed or created unless the respective switch is supplied. Use -WhatIf
    with -CreateGroups to preview group creation.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$InstallRsat,
    [switch]$CreateGroups,
    [string[]]$WorkstationIds = @("WS-001", "WS-002"),
    [string]$GroupPrefix = "RDP-",
    [string]$OrganizationalUnit
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($InstallRsat -and -not (Test-IsAdministrator)) {
    throw "Für die RSAT-Installation PowerShell als Administrator starten."
}

if ($InstallRsat) {
    $capability = Get-WindowsCapability -Online -Name "Rsat.ActiveDirectory.DS-LDS.Tools*"
    if ($capability.State -ne "Installed") {
        Write-Host "Installiere RSAT Active Directory Tools …"
        Add-WindowsCapability -Online -Name $capability.Name
    } else {
        Write-Host "RSAT Active Directory Tools sind bereits installiert."
    }
}

if (-not $CreateGroups) {
    Write-Host "Keine AD-Gruppen verändert. Für die Anlage -CreateGroups angeben."
    exit 0
}

Import-Module ActiveDirectory -ErrorAction Stop
foreach ($workstationId in $WorkstationIds) {
    $name = "$GroupPrefix$workstationId"
    $existing = Get-ADGroup -Filter "SamAccountName -eq '$($name.Replace("'", "''"))'" -ErrorAction Stop
    if ($existing) {
        Write-Host "Vorhanden: $name"
        continue
    }
    $parameters = @{
        Name          = $name
        SamAccountName = $name
        GroupScope    = "Global"
        GroupCategory = "Security"
        Description   = "RDP-Zugriff für $workstationId (Kirschke RDP Portal)"
    }
    if ($OrganizationalUnit) {
        $parameters.Path = $OrganizationalUnit
    }
    if ($PSCmdlet.ShouldProcess($name, "AD-Sicherheitsgruppe erstellen")) {
        New-ADGroup @parameters | Out-Null
        Write-Host "Erstellt: $name"
    }
}
