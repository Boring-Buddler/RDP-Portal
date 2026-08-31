[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    [string]$WorkstationId,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$StatusDirectory,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$SourceDirectory,

    [ValidateRange(5, 3600)]
    [int]$PollInterval = 30,

    [switch]$StartNow,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$taskName = "Kirschke RDP Agent - $WorkstationId"
$installDirectory = Join-Path $env:LOCALAPPDATA "KirschkeRDPAgent"
$configPath = Join-Path $installDirectory "agent-config.json"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Autostart entfernt: $taskName"
    Write-Host "Programmdateien und Status bleiben zur Pruefung erhalten: $installDirectory"
    exit 0
}

$source = (Resolve-Path -LiteralPath $SourceDirectory).Path
$sourceExecutable = Join-Path $source "Kirschke-RDP-Agent.exe"
if (-not (Test-Path -LiteralPath $sourceExecutable)) {
    throw "Kirschke-RDP-Agent.exe wurde nicht gefunden: $sourceExecutable"
}

New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
Get-ChildItem -LiteralPath $source -Force | Copy-Item -Destination $installDirectory -Recurse -Force
$agentExecutable = Join-Path $installDirectory "Kirschke-RDP-Agent.exe"

$config = [ordered]@{
    workstation_id = $WorkstationId
    poll_interval = $PollInterval
    publish_local_status = $true
    status_directory = $StatusDirectory
    log_file = (Join-Path $installDirectory "agent.log")
    agent_version = "1.0.0"
}
$config | ConvertTo-Json | Set-Content -LiteralPath $configPath -Encoding UTF8

$arguments = "--config `"$configPath`" --run"
$action = New-ScheduledTaskAction -Execute $agentExecutable -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null

Write-Host "Agent eingerichtet: $agentExecutable"
Write-Host "Konfiguration: $configPath"
Write-Host "Statusziel: $StatusDirectory"
Write-Host "Autostart: beim Anmelden von $env:USERDOMAIN\$env:USERNAME"

if ($StartNow) {
    Start-Process -FilePath $agentExecutable -ArgumentList @("--config", $configPath, "--run") -WindowStyle Hidden
    Write-Host "Agent wurde gestartet."
}
