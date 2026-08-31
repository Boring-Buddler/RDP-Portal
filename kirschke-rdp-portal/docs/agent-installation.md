# Kirschke RDP-Agent installieren

Der Agent ist optional. Ohne Agent kann das Portal nur Erreichbarkeit (Ping), den RDP-Port und lokal gestartete
`mstsc`-Fenster bewerten. Es kann ohne Remoteverwaltung nicht zuverlässig erkennen, wer auf einem Ziel-PC angemeldet
ist oder ob die Sitzung nur getrennt wurde.

Der portable Agent liest auf dem Ziel-PC die Windows-Remotedesktop-Sitzungen über die WTS-API und schreibt alle
30 Sekunden eine kleine Statusdatei. Das Portal liest sie automatisch aus seinem gemeinsamen Speicherordner im
Unterordner `agent-status` ein.

## Voraussetzungen

- Der Ziel-PC läuft mit Windows und darf Remotedesktop-Sitzungen annehmen.
- Der angemeldete Benutzer kann den gemeinsamen Portalordner erreichen, etwa über die synchronisierte
  SharePoint-Bibliothek.
- Die Maschinen-ID im Portal steht fest, zum Beispiel `WS-001`.
- Für den Pilotbetrieb genügt ein normaler Benutzer. Der Autostart erfolgt beim Anmelden dieses Benutzers.

Die Dateien enthalten nur Verbindungsstatus, Windows-Sitzungs-ID und den bei Windows sichtbaren Anmeldenamen – keine
Kennwörter und keine RDP-Dateien.

## 1. Standalone-Agenten bauen

Auf dem Entwicklungs-PC im Projektordner ausführen:

```powershell
.\deployment\build_agent.cmd
```

Danach liegt die vollständige portable Ausgabe hier:

```text
dist-agent\Kirschke-RDP-Agent\
```

Den kompletten Ordner auf den Ziel-PC kopieren. Er enthält die EXE und `Install-Agent.ps1`; Python muss dort nicht
installiert sein.

## 2. Gemeinsamen Statusordner bestimmen

Im Portal unter **Einstellungen** den gemeinsamen Speicherort prüfen. Der Agent benötigt genau diesen Ordner mit
angehängtem Unterordner `agent-status`, beispielsweise:

```text
C:\Users\becker\Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG\IB Kirschke - Dokumente\90\_K.I. Strategie\Testprogramme\RDP-Portal\agent-status
```

Auf jedem Ziel-PC muss dieser Pfad für den Benutzer erreichbar sein. Bei OneDrive/SharePoint bedeutet das: die
Bibliothek muss dort synchronisiert sein. Ist der lokale OneDrive-Pfad anders, ist das in Ordnung – entscheidend ist,
dass er in dieselbe Bibliothek und denselben Ordner schreibt.

## 3. Agent installieren und sofort testen

Auf dem Ziel-PC PowerShell im kopierten Agentenordner öffnen und folgenden Befehl anpassen:

```powershell
.\Install-Agent.ps1 `
  -WorkstationId "WS-001" `
  -SourceDirectory "C:\Temp\Kirschke-RDP-Agent" `
  -StatusDirectory "C:\Users\becker\Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG\IB Kirschke - Dokumente\90\_K.I. Strategie\Testprogramme\RDP-Portal\agent-status" `
  -StartNow
```

`SourceDirectory` ist der Ordner, in dem direkt `Kirschke-RDP-Agent.exe` liegt. Das Skript kopiert ihn nach
`%LOCALAPPDATA%\KirschkeRDPAgent`, schreibt dort `agent-config.json` und registriert einen Autostart für den aktuell
angemeldeten Windows-Benutzer.

Falls PowerShell Skripte sperrt, einmalig so starten:

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-Agent.ps1 -WorkstationId "WS-001" -SourceDirectory "C:\Temp\Kirschke-RDP-Agent" -StatusDirectory "C:\Pfad\zum\RDP-Portal\agent-status" -StartNow
```

## 4. Ergebnis prüfen

Nach höchstens 30 Sekunden im Portal **Einstellungen** öffnen. Bei der Agent-Statusanzeige muss die Maschine gezählt
werden. Zusätzlich kann auf dem Ziel-PC eine Einmaldiagnose laufen:

```powershell
& "$env:LOCALAPPDATA\KirschkeRDPAgent\Kirschke-RDP-Agent.exe" --config "$env:LOCALAPPDATA\KirschkeRDPAgent\agent-config.json" --status
```

Die Statusdatei heißt `<Maschinen-ID>.json` und liegt im oben gewählten `agent-status`-Ordner. Bei Problemen zuerst
`%LOCALAPPDATA%\KirschkeRDPAgent\agent.log` und den OneDrive-Synchronisationsstatus prüfen.

## Deinstallieren

Das entfernt nur den Autostart; Konfiguration und Log bleiben zur Diagnose erhalten:

```powershell
.\Install-Agent.ps1 -WorkstationId "WS-001" -StatusDirectory "x" -SourceDirectory "x" -Uninstall
```

## Wichtige Grenze des Pilotbetriebs

Der Autostart läuft im Kontext des angemeldeten Benutzers. Meldet sich dieser vollständig ab, beendet Windows auch den
Agenten. Ein dauerhafter Windows-Dienst wäre möglich, benötigt ohne AD/verwaltetes Dienstkonto aber eine bewusst
eingerichtete Berechtigung auf den gemeinsamen Speicher. Das ist deshalb nicht automatisch aktiviert.
