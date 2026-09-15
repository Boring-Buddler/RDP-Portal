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

# Agent und Portal tragen dasselbe Symbol: auf dem Zielrechner taucht der
# Agent im Explorer und in der Dienstliste auf, und ein Standardsymbol dort
# sieht aus wie ein fremdes Programm.
$icon = Join-Path $projectRoot "portal_app\ui\assets\kirschke.ico"
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Anwendungssymbol fehlt: $icon (python deployment/build_app_icon.py)"
}

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "Kirschke-RDP-Agent",
    "--icon", $icon,
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
$installerSource = Join-Path $PSScriptRoot "install_agent.ps1"
$installerDirectory = Split-Path -Parent $target
$installer = Join-Path $installerDirectory "Install-Agent.ps1"
# Windows PowerShell 5.1 needs a BOM to interpret German UI text as UTF-8.
[System.IO.File]::WriteAllText($installer, [System.IO.File]::ReadAllText($installerSource, [System.Text.Encoding]::UTF8), [System.Text.UTF8Encoding]::new($true))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "Install-Agent.cmd") -Destination (Join-Path $installerDirectory "Install-Agent.cmd") -Force
Write-Host "Build fertig: $target"
Write-Host "Installer: $(Join-Path $installerDirectory 'Install-Agent.cmd')"

# The setup is a single file. Its temporary payload stays alive until the GUI
# installer has copied the agent to the user's permanent installation folder.
$setupArguments = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
    "--name", "Kirschke-RDP-Agent-Setup", "--uac-admin",
    "--icon", $icon,
    "--distpath", $outputRoot,
    "--workpath", (Join-Path $workRoot "setup"),
    "--specpath", $specRoot,
    "--add-data", "$installerDirectory;payload",
    (Join-Path $PSScriptRoot "agent_installer.py")
)
& python @setupArguments
if ($LASTEXITCODE -ne 0) { throw "Der Setup-Build ist fehlgeschlagen: $LASTEXITCODE" }
Write-Host "Setup-EXE: $(Join-Path $outputRoot 'Kirschke-RDP-Agent-Setup.exe')"
