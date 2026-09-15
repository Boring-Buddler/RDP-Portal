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
# Ohne --icon traegt die EXE das PyInstaller-Standardsymbol. Das ist das
# Symbol, das die Taskleiste, der Explorer und jede Verknuepfung zeigen --
# setWindowIcon zur Laufzeit erreicht keines davon.
$icon = Join-Path $assets "kirschke.ico"
if (-not (Test-Path -LiteralPath $icon)) {
    throw "Anwendungssymbol fehlt: $icon (python deployment/build_app_icon.py)"
}

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Einstiegspunkt nicht gefunden: $entryPoint"
}

$arguments = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "Kirschke-RDP-Portal",
    "--icon", $icon,
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
if (-not $OneFile) {
    $payload = Split-Path -Parent $target
    $installer = Join-Path $payload 'Install-Portal.ps1'
    # Die Versionsnummer kommt aus shared/version.py, damit die Windows-
    # Programmliste nicht wieder auf einem alten Stand stehen bleibt.
    $versionFile = Join-Path $projectRoot 'shared\version.py'
    $portalVersion = ([regex]::Match((Get-Content -LiteralPath $versionFile -Raw), 'PORTAL_VERSION\s*=\s*"([^"]+)"')).Groups[1].Value
    if (-not $portalVersion) { throw "PORTAL_VERSION nicht gefunden in $versionFile" }
    $installerText = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'install_portal.ps1'), [System.Text.Encoding]::UTF8)
    $installerText = $installerText.Replace("`$portalVersion = '0.0.0-dev'", "`$portalVersion = '$portalVersion'")
    [System.IO.File]::WriteAllText($installer, $installerText, [System.Text.UTF8Encoding]::new($true))
    & python -m PyInstaller --noconfirm --clean --onefile --windowed --name Kirschke-RDP-Portal-Setup --icon $icon --distpath $outputRoot --workpath (Join-Path $workRoot 'setup') --specpath $specRoot --add-data "$payload;payload" --add-data "$installer;." (Join-Path $PSScriptRoot 'portal_installer.py')
    if ($LASTEXITCODE -ne 0) { throw 'Portal-Setup-Build fehlgeschlagen.' }
}
