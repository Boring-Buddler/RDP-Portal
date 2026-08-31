[CmdletBinding()]
param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$outputRoot = Join-Path $projectRoot "dist"
$workRoot = Join-Path $projectRoot "build"
$specRoot = Join-Path $projectRoot "build-spec"
$entryPoint = Join-Path $projectRoot "portal_app\app.py"
$assets = Join-Path $projectRoot "portal_app\ui\assets"

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Einstiegspunkt nicht gefunden: $entryPoint"
}

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "Kirschke-RDP-Portal",
    "--paths", $projectRoot,
    "--add-data", "$assets;portal_app\ui\assets",
    "--distpath", $outputRoot,
    "--workpath", $workRoot,
    "--specpath", $specRoot
)

if ($OneFile) {
    $arguments += "--onefile"
} else {
    # Qt applications start faster and are easier to diagnose as a folder build.
    $arguments += "--onedir"
}

$arguments += $entryPoint
& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Der PyInstaller-Build wurde mit Fehlercode $LASTEXITCODE beendet."
}

$target = if ($OneFile) {
    Join-Path $outputRoot "Kirschke-RDP-Portal.exe"
} else {
    Join-Path $outputRoot "Kirschke-RDP-Portal\Kirschke-RDP-Portal.exe"
}

Write-Host "Build fertig: $target"
