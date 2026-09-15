[CmdletBinding()]
param([string]$SourceDirectory, [switch]$Uninstall, [switch]$NoUi)
$ErrorActionPreference = 'Stop'
$installDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\KirschkeRDPPortal'
$registry = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KirschkeRDPPortal'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Kirschke RDP Portal.lnk'
# Wird vom Build aus shared/version.py ersetzt. Vorher stand hier eine feste
# Nummer, die drei Versionen lang nicht mitgezogen wurde und in der
# Windows-Programmliste eine falsche Version auswies.
$portalVersion = '0.0.0-dev'

function Remove-Portal {
    $executable = Join-Path $installDirectory 'Kirschke-RDP-Portal.exe'
    $running = @(Get-Process -Name 'Kirschke-RDP-Portal' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable })
    if ($running.Count) { throw 'Bitte das installierte Portal vor der Installation oder Deinstallation schließen.' }
    if (Test-Path -LiteralPath $installDirectory) {
        $resolved = (Resolve-Path -LiteralPath $installDirectory).Path.TrimEnd('\')
        if ($resolved -ne [System.IO.Path]::GetFullPath($installDirectory).TrimEnd('\') -or
            (Split-Path -Leaf $resolved) -ne 'KirschkeRDPPortal') { throw 'Ungültiger Portal-Installationspfad.' }
        $items = @(Get-Item -LiteralPath $resolved) + @(Get-ChildItem -LiteralPath $resolved -Force -Recurse)
        if (@($items | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }).Count) {
            throw 'Verknüpfung im Installationsordner; keine automatische Löschung.'
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force }
    if (Test-Path -LiteralPath $registry) { Remove-Item -LiteralPath $registry -Force }
}

function Install-Portal {
    $source = (Resolve-Path -LiteralPath $SourceDirectory).Path
    if (-not (Test-Path -LiteralPath (Join-Path $source 'Kirschke-RDP-Portal.exe'))) { throw 'Portaldateien fehlen.' }
    if ($source.TrimEnd('\') -eq $installDirectory.TrimEnd('\')) { throw 'Setup aus dem separaten Installationspaket starten.' }
    Remove-Portal
    New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
    Copy-Item -Path (Join-Path $source '*') -Destination $installDirectory -Recurse -Force
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = Join-Path $installDirectory 'Kirschke-RDP-Portal.exe'
    $link.WorkingDirectory = $installDirectory
    # Explizit gesetzt, damit die Verknuepfung das Symbol auch dann zeigt,
    # wenn Windows seinen Symbol-Cache nicht neu aufbaut.
    $link.IconLocation = "$(Join-Path $installDirectory 'Kirschke-RDP-Portal.exe'),0"
    $link.Save()
    New-Item -Path $registry -Force | Out-Null
    New-ItemProperty -Path $registry -Name DisplayName -Value 'Kirschke RDP Portal' -Force | Out-Null
    New-ItemProperty -Path $registry -Name DisplayVersion -Value $portalVersion -Force | Out-Null
    $command = "powershell.exe -NoProfile -File `"$(Join-Path $installDirectory 'Install-Portal.ps1')`" -Uninstall"
    New-ItemProperty -Path $registry -Name UninstallString -Value $command -Force | Out-Null
}

if ($NoUi) {
    if ($Uninstall) { Remove-Portal } else { Install-Portal }
    exit 0
}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = "Kirschke RDP Portal $portalVersion – Setup"
$form.ClientSize = New-Object System.Drawing.Size(570, 220)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$label = New-Object System.Windows.Forms.Label
$label.Text = "Portal $portalVersion für diesen Benutzer installieren.`n`nAlte installierte Programmdateien werden vor der Neuinstallation entfernt. Maschinen, Reservierungen und Einstellungen bleiben erhalten.`n`nZiel: $installDirectory"
$label.Location = New-Object System.Drawing.Point(20, 20)
$label.Size = New-Object System.Drawing.Size(530, 140)
$form.Controls.Add($label)
$button = New-Object System.Windows.Forms.Button
$button.Text = if ($Uninstall) { 'Deinstallieren' } else { 'Installieren' }
$button.Location = New-Object System.Drawing.Point(360, 175)
$button.Size = New-Object System.Drawing.Size(190, 32)
$button.Add_Click({
    try {
        if ($Uninstall) { Remove-Portal } else { Install-Portal }
        [System.Windows.Forms.MessageBox]::Show('Vorgang abgeschlossen. Maschinen und Einstellungen bleiben erhalten.', 'Portal-Setup') | Out-Null
        $form.Close()
    } catch { [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Portal-Setup') | Out-Null }
})
$form.Controls.Add($button)
[void]$form.ShowDialog()
