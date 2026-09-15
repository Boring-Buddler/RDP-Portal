[CmdletBinding()]
param(
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
    [string]$WorkstationId,
    [string]$StatusDirectory,
    [string]$SourceDirectory,
    [ValidateRange(5, 60)]
    [int]$PollInterval = 30,
    [switch]$StartNow,
    [switch]$Uninstall,
    [switch]$NoUi
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:InstallDirectory = Join-Path $env:ProgramFiles "KirschkeRDPAgent"
$script:DataDirectory = Join-Path $env:ProgramData "KirschkeRDPAgent"
$script:ConfigPath = Join-Path $script:DataDirectory "agent-config.json"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    if ($Uninstall) {
        $child = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile', '-File', ('"' + $PSCommandPath + '"'), '-Uninstall')
        exit $child.ExitCode
    }
    throw "Die rechnerweite Agent-Installation muss als Administrator gestartet werden."
}

function Get-DefaultStatusDirectory {
    return "C:\RDP-Portal-Daten\agenten-status"
}

function Test-StatusDirectoryAccess {
    param([Parameter(Mandatory)][string]$Directory)
    try {
        New-Item -ItemType Directory -Path $Directory -Force | Out-Null
        $probe = Join-Path $Directory (".kirschke-agent-write-test-" + [guid]::NewGuid().ToString("N") + ".tmp")
        [System.IO.File]::WriteAllText($probe, "ok", [System.Text.Encoding]::UTF8)
        Remove-Item -LiteralPath $probe -Force
        return $true
    } catch {
        throw "Der Statusordner kann nicht beschrieben werden: $Directory`n$($_.Exception.Message)"
    }
}

function Get-AgentInstallDirectories {
    $script:InstallDirectory
    foreach ($profile in @(Get-CimInstance Win32_UserProfile | Where-Object { -not $_.Special -and $_.LocalPath })) {
        Join-Path $profile.LocalPath 'AppData\Local\KirschkeRDPAgent'
    }
}

function Install-Agent {
    param(
        [Parameter(Mandatory)][string]$SelectedWorkstationId,
        [Parameter(Mandatory)][string]$SelectedStatusDirectory,
        [Parameter(Mandatory)][string]$SelectedSourceDirectory,
        [Parameter(Mandatory)][int]$SelectedPollInterval,
        [bool]$LaunchNow = $true
    )
    $source = (Resolve-Path -LiteralPath $SelectedSourceDirectory).Path
    $sourceExecutable = Join-Path $source "Kirschke-RDP-Agent.exe"
    if (-not (Test-Path -LiteralPath $sourceExecutable -PathType Leaf)) {
        throw "Kirschke-RDP-Agent.exe wurde nicht gefunden. Starten Sie Install-Agent.cmd aus dem entpackten Agentenordner."
    }
    if ($source.TrimEnd("\\") -eq $script:InstallDirectory.TrimEnd("\\")) {
        throw "Der Installer darf nicht aus dem Installationsordner selbst ausgeführt werden."
    }
    $SelectedStatusDirectory = [Environment]::ExpandEnvironmentVariables($SelectedStatusDirectory.Trim())
    if (-not [System.IO.Path]::IsPathRooted($SelectedStatusDirectory) -or $SelectedStatusDirectory -match '%[^%]+%') {
        throw "Bitte einen vollständigen lokalen oder Netzwerkpfad angeben. Umgebungsvariablen müssen auf diesem PC vorhanden sein."
    }
    Test-StatusDirectoryAccess -Directory $SelectedStatusDirectory | Out-Null
    $SelectedStatusDirectory = (Resolve-Path -LiteralPath $SelectedStatusDirectory).Path
    foreach ($oldDirectory in @(Get-AgentInstallDirectories)) {
        $oldRoot = [System.IO.Path]::GetFullPath($oldDirectory).TrimEnd('\')
        foreach ($checkedPath in @($source, $SelectedStatusDirectory)) {
            if ($checkedPath -eq $oldRoot -or $checkedPath.StartsWith($oldRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "Installationsquelle und Statusordner müssen außerhalb alter Agent-Installationen liegen: $oldRoot"
            }
        }
    }

    # One configured agent per Windows profile; remove only our own old task.
    Uninstall-Agent | Out-Null

    $taskName = "Kirschke RDP Agent - Machine"
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $script:InstallDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $script:DataDirectory -Force | Out-Null
    & icacls.exe $script:DataDirectory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Agent-Datenverzeichnis konnte nicht abgesichert werden." }
    Copy-Item -Path (Join-Path $source "*") -Destination $script:InstallDirectory -Recurse -Force
    $agentExecutable = Join-Path $script:InstallDirectory "Kirschke-RDP-Agent.exe"
    $config = [ordered]@{
        workstation_id = $SelectedWorkstationId
        poll_interval = $SelectedPollInterval
        publish_local_status = $true
        live_status_enabled = $true
        live_status_reader = "PortalLeser"
        status_directory = $SelectedStatusDirectory
        log_file = (Join-Path $script:DataDirectory "agent.log")
        agent_version = "1.3.0"
    }
    $config | ConvertTo-Json | Set-Content -LiteralPath $script:ConfigPath -Encoding UTF8
    $arguments = "--config `"$script:ConfigPath`" --run"
    $action = New-ScheduledTaskAction -Execute $agentExecutable -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "Kirschke RDP-Agent: veröffentlicht den Sitzungsstatus von $SelectedWorkstationId." -Force | Out-Null
    $uninstallCommand = "powershell.exe -NoProfile -File `"$(Join-Path $script:InstallDirectory 'Install-Agent.ps1')`" -Uninstall"
    $registry = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KirschkeRDPAgent'
    New-Item -Path $registry -Force | Out-Null
    New-ItemProperty -Path $registry -Name DisplayName -Value 'Kirschke RDP Agent' -Force | Out-Null
    New-ItemProperty -Path $registry -Name DisplayVersion -Value '1.3.0' -Force | Out-Null
    New-ItemProperty -Path $registry -Name UninstallString -Value $uninstallCommand -Force | Out-Null
    if ($LaunchNow) {
        $startedAt = [DateTimeOffset]::UtcNow
        Start-ScheduledTask -TaskName $taskName
        $snapshotPath = Join-Path $SelectedStatusDirectory "$SelectedWorkstationId.json"
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(20)
        $confirmed = $false
        do {
            Start-Sleep -Milliseconds 500
            try {
                $snapshot = Get-Content -LiteralPath $snapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
                $confirmed = ($snapshot.workstation_id -eq $SelectedWorkstationId) -and
                    ($snapshot.hostname -eq $env:COMPUTERNAME) -and
                    ($snapshot.agent_status -eq "online") -and
                    ([DateTimeOffset]::Parse($snapshot.observed_at_utc) -ge $startedAt)
            } catch { $confirmed = $false }
        } until ($confirmed -or [DateTimeOffset]::UtcNow -ge $deadline)
        if (-not $confirmed) {
            throw "Der System-Agent wurde eingerichtet, hat aber keinen aktuellen Online-Status geschrieben. Prüfen Sie die Aufgabenplanung, die Schreibrechte für das Computerkonto und $script:DataDirectory\agent.log."
        }
    }
    return [pscustomobject]@{ TaskName = $taskName; AgentExecutable = $agentExecutable; StatusDirectory = $SelectedStatusDirectory }
}

function Uninstall-Agent {
    $ownedDirectories = @(Get-AgentInstallDirectories)
    $ownedExecutables = @($ownedDirectories | ForEach-Object { Join-Path $_ 'Kirschke-RDP-Agent.exe' })
    $tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {
        $_.TaskName -like "Kirschke RDP Agent - *" -and
        @($_.Actions | Where-Object { $_.Execute -in $ownedExecutables }).Count -gt 0
    })
    foreach ($task in $tasks) {
        Stop-ScheduledTask -TaskName $task.TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $task.TaskName -Confirm:$false
    }
    foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='Kirschke-RDP-Agent.exe'")) {
        if ($process.ExecutablePath -in $ownedExecutables) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        }
    }
    foreach ($directory in $ownedDirectories) {
        if (-not (Test-Path -LiteralPath $directory)) { continue }
        $resolved = (Resolve-Path -LiteralPath $directory).Path.TrimEnd('\')
        if ($resolved -ne [System.IO.Path]::GetFullPath($directory).TrimEnd('\') -or
            (Split-Path -Leaf $resolved) -ne 'KirschkeRDPAgent') { throw 'Ungültiger Agent-Deinstallationspfad.' }
        $links = @(Get-Item -LiteralPath $resolved) + @(Get-ChildItem -LiteralPath $resolved -Recurse -Force)
        if (@($links | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }).Count) {
            throw "Verknüpfung im Installationsordner; keine automatische Löschung: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    if (Test-Path -LiteralPath $script:ConfigPath) { Remove-Item -LiteralPath $script:ConfigPath -Force }
    Remove-Item -LiteralPath 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\KirschkeRDPAgent' -ErrorAction SilentlyContinue
    return @($tasks).Count
}

function Show-Installer {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "Kirschke RDP-Agent installieren"
    $form.StartPosition = "CenterScreen"
    $form.ClientSize = New-Object System.Drawing.Size(640, 410)
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.Font = New-Object System.Drawing.Font("Segoe UI", 9)

    $title = New-Object System.Windows.Forms.Label
    $title.Text = "RDP-Agent auf diesem Ziel-PC einrichten"
    $title.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 14)
    $title.AutoSize = $true; $title.Location = New-Object System.Drawing.Point(24, 20)
    $form.Controls.Add($title)
    $intro = New-Object System.Windows.Forms.Label
    $intro.Text = "Rechnerweiter Start beim Hochfahren als SYSTEM, auch ohne Benutzeranmeldung. Alte Agent-Installationen werden entfernt. Administratorrechte erforderlich."
    $intro.AutoSize = $false; $intro.Size = New-Object System.Drawing.Size(590, 44); $intro.Location = New-Object System.Drawing.Point(24, 54)
    $form.Controls.Add($intro)

    $idLabel = New-Object System.Windows.Forms.Label
    $idLabel.Text = "Maschinen-ID im Portal"; $idLabel.AutoSize = $true; $idLabel.Location = New-Object System.Drawing.Point(24, 118)
    $form.Controls.Add($idLabel)
    $idBox = New-Object System.Windows.Forms.TextBox
    $idBox.Text = if ($WorkstationId) { $WorkstationId } else { $env:COMPUTERNAME }
    $idBox.Size = New-Object System.Drawing.Size(590, 24); $idBox.Location = New-Object System.Drawing.Point(24, 140)
    $form.Controls.Add($idBox)

    $folderLabel = New-Object System.Windows.Forms.Label
    $folderLabel.Text = "Lokaler Statusordner auf diesem Zielrechner"; $folderLabel.AutoSize = $true; $folderLabel.Location = New-Object System.Drawing.Point(24, 178)
    $form.Controls.Add($folderLabel)
    $folderBox = New-Object System.Windows.Forms.TextBox
    $folderBox.Text = if ($StatusDirectory) { $StatusDirectory } else { Get-DefaultStatusDirectory }
    $folderBox.Size = New-Object System.Drawing.Size(490, 24); $folderBox.Location = New-Object System.Drawing.Point(24, 200)
    $form.Controls.Add($folderBox)
    $browseButton = New-Object System.Windows.Forms.Button
    $browseButton.Text = "Auswählen..."; $browseButton.Size = New-Object System.Drawing.Size(100, 25); $browseButton.Location = New-Object System.Drawing.Point(514, 199)
    $browseButton.Add_Click({
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Lokalen Ordner auswählen, in den der Agent als SYSTEM schreiben darf"
        $dialog.SelectedPath = $folderBox.Text
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $folderBox.Text = $dialog.SelectedPath }
    })
    $form.Controls.Add($browseButton)
    $hint = New-Object System.Windows.Forms.Label
    $hint.Text = "Empfohlen: C:\RDP-Portal-Daten\agenten-status. Der Agent schreibt lokal als SYSTEM. Das Portal liest den maschinenspezifischen SMB-Fallback unter \\RECHNER\RDP-Status; PortalLeser bleibt ein reines Lesekonto."
    $hint.AutoSize = $false; $hint.Size = New-Object System.Drawing.Size(590, 70); $hint.Location = New-Object System.Drawing.Point(24, 235); $hint.ForeColor = [System.Drawing.Color]::FromArgb(70, 70, 70)
    $form.Controls.Add($hint)
    $intervalLabel = New-Object System.Windows.Forms.Label
    $intervalLabel.Text = "Aktualisierung"; $intervalLabel.AutoSize = $true; $intervalLabel.Location = New-Object System.Drawing.Point(24, 318)
    $form.Controls.Add($intervalLabel)
    $intervalBox = New-Object System.Windows.Forms.ComboBox
    $intervalBox.DropDownStyle = "DropDownList"; [void]$intervalBox.Items.AddRange([object[]]@("30 Sekunden (empfohlen)", "60 Sekunden", "15 Sekunden")); $intervalBox.SelectedIndex = 0
    $intervalBox.Size = New-Object System.Drawing.Size(210, 24); $intervalBox.Location = New-Object System.Drawing.Point(120, 314)
    $form.Controls.Add($intervalBox)

    $installButton = New-Object System.Windows.Forms.Button
    $installButton.Text = "Jetzt installieren"; $installButton.Size = New-Object System.Drawing.Size(150, 34); $installButton.Location = New-Object System.Drawing.Point(350, 354)
    $installButton.Font = New-Object System.Drawing.Font("Segoe UI Semibold", 9)
    $installButton.Add_Click({
        $selectedId = $idBox.Text.Trim(); $selectedDirectory = $folderBox.Text.Trim()
        if ($selectedId -notmatch "^[A-Za-z0-9][A-Za-z0-9_.-]*$") {
            [System.Windows.Forms.MessageBox]::Show("Bitte geben Sie die Maschinen-ID exakt wie im Portal an. Erlaubt sind Buchstaben, Zahlen, Punkt, Unterstrich und Bindestrich.", "Maschinen-ID prüfen", "OK", "Warning") | Out-Null; return
        }
        if (-not $selectedDirectory) {
            [System.Windows.Forms.MessageBox]::Show("Bitte wählen Sie den lokalen Agent-Statusordner aus.", "Statusordner fehlt", "OK", "Warning") | Out-Null; return
        }
        try {
            $seconds = @(30, 60, 15)[$intervalBox.SelectedIndex]
            $result = Install-Agent -SelectedWorkstationId $selectedId -SelectedStatusDirectory $selectedDirectory -SelectedSourceDirectory $SourceDirectory -SelectedPollInterval $seconds -LaunchNow $true
            [System.Windows.Forms.MessageBox]::Show("Der Agent wurde eingerichtet und gestartet.`n`nMaschinen-ID: $selectedId`nStatusordner: $($result.StatusDirectory)`n`nPrüfen Sie nach etwa 30 Sekunden im Portal den Agentenstatus.", "Installation abgeschlossen", "OK", "Information") | Out-Null
            $form.Close()
        } catch {
            [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "Installation nicht möglich", "OK", "Error") | Out-Null
        }
    })
    $form.Controls.Add($installButton)
    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Abbrechen"; $cancelButton.Size = New-Object System.Drawing.Size(100, 34); $cancelButton.Location = New-Object System.Drawing.Point(514, 354)
    $cancelButton.Add_Click({ $form.Close() }); $form.Controls.Add($cancelButton)
    [void]$form.ShowDialog()
}

if ($Uninstall) {
    $removed = Uninstall-Agent
    if ($NoUi) { Write-Host "Agent entfernt: $removed Aufgabe(n), Programmdateien und Konfiguration. Zentrale Statusdaten bleiben erhalten." }
    else {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show("Autostart, Programmdateien und Konfiguration wurden entfernt. Zentrale Statusdateien und rechnerweite Logs bleiben erhalten.", "Kirschke RDP-Agent", "OK", "Information") | Out-Null
    }
    exit 0
}
if (-not $SourceDirectory) { $SourceDirectory = $PSScriptRoot }
if ($NoUi -or ($WorkstationId -and $StatusDirectory)) {
    if (-not $WorkstationId -or -not $StatusDirectory) { throw "Für eine unbeaufsichtigte Installation sind -WorkstationId und -StatusDirectory erforderlich." }
    $result = Install-Agent -SelectedWorkstationId $WorkstationId -SelectedStatusDirectory $StatusDirectory -SelectedSourceDirectory $SourceDirectory -SelectedPollInterval $PollInterval -LaunchNow ($StartNow -or $NoUi)
    Write-Host "Agent eingerichtet: $($result.AgentExecutable)"
    Write-Host "Statusziel: $($result.StatusDirectory)"
    exit 0
}
Show-Installer
