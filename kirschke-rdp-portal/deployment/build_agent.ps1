[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot "dist-agent"
$workRoot = Join-Path $projectRoot "agent-build"
$specRoot = Join-Path $projectRoot "agent-build-spec"
$entryPoint = Join-Path $projectRoot "workstation_agent\agent_app.py"

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Einstiegspunkt nicht gefunden: $entryPoint"
}

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--console",
    "--name", "Kirschke-RDP-Agent",
    "--paths", $projectRoot,
    "--distpath", $outputRoot,
    "--workpath", $workRoot,
    "--specpath", $specRoot,
    $entryPoint
)

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Der PyInstaller-Build wurde mit Fehlercode $LASTEXITCODE beendet."
}

$target = Join-Path $outputRoot "Kirschke-RDP-Agent\Kirschke-RDP-Agent.exe"
$installer = Join-Path $PSScriptRoot "install_agent.ps1"
Copy-Item -LiteralPath $installer -Destination (Join-Path (Split-Path -Parent $target) "Install-Agent.ps1") -Force
Write-Host "Build fertig: $target"
Write-Host "Installer: $(Join-Path (Split-Path -Parent $target) 'Install-Agent.ps1')"
