# Kirschke RDP-Agent installieren

Stand 09.09.2026: Siehe [Prüfbericht und Pilotabnahme](code-review-testbetrieb.md).
Der Installer startet den Agent über dieselbe geplante Aufgabe wie beim Anmelden,
mit korrekt zitiertem Konfigurationspfad und ohne das standardmäßige 72-Stunden-Laufzeitlimit.
Erlaubtes Aktualisierungsintervall: 5–60 Sekunden. Die alten Schalter für eine
Windows-Dienstinstallation werden mit einer Fehlermeldung abgewiesen; dieser
Bereitstellungsweg ist noch nicht betriebsbereit.

Der Agent ist optional. Ohne Agent kann das Portal nur Erreichbarkeit (Ping), den RDP-Port und lokal gestartete
`mstsc`-Fenster bewerten. Es kann ohne Remoteverwaltung nicht zuverlässig erkennen, wer auf einem Ziel-PC angemeldet
ist oder ob die Sitzung nur getrennt wurde.

Der portable Agent liest auf dem Ziel-PC die Windows-Remotedesktop-Sitzungen über die WTS-API und schreibt alle
30 Sekunden eine kleine Statusdatei. Das Portal liest sie aus dem unter
**Einstellungen → Windows-Agent** gewählten exakten Statusordner ein.

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

Zusätzlich entsteht `dist-agent\Kirschke-RDP-Agent-Setup.exe`. Diese einzelne Datei
auf den Ziel-PC kopieren; sie enthält den Agenten und den grafischen Installer.
Alternativ den kompletten portablen Ordner mit `Install-Agent.cmd` verwenden.
Python muss auf dem Ziel-PC nicht installiert sein.

## 2. Gemeinsamen Statusordner bestimmen

Im Portal unter **Einstellungen → Windows-Agent** den Ordner mit den Agent-JSON-Dateien
einstellen. Im Agent-Setup denselben synchronisierten Ordner auswählen. Es wird kein
weiterer Unterordner angehängt. Der Standard ist:

```text
%USERPROFILE%\Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG\IB Kirschke - Dokumente\90\_K.I. Strategie\Testprogramme\RDP-Portal\remote\agenten-status
```

Auf jedem Ziel-PC muss dieser Pfad für den Benutzer erreichbar sein. Bei OneDrive/SharePoint bedeutet das: die
Bibliothek muss dort synchronisiert sein. Ist der lokale OneDrive-Pfad anders, ist das in Ordnung – entscheidend ist,
dass er in dieselbe Bibliothek und denselben Ordner schreibt.

## 3. Agent mit einem Klick installieren

Auf dem Ziel-PC `Kirschke-RDP-Agent-Setup.exe` doppelklicken (alternativ im vollständigen
portablen Agentenordner `Install-Agent.cmd`). Der Installer startet ohne
PowerShell-Eingaben und erklärt die zwei Angaben, die nicht sicher automatisch ermittelt werden können:

1. **Maschinen-ID:** exakt die ID der registrierten Maschine im Portal, etwa `WS-001`. Der lokale Computername wird
   als Vorschlag eingetragen.
2. **Gemeinsamer Statusordner:** exakt den Ordner aus **Einstellungen → Windows-Agent**
   auswählen. `%USERPROFILE%` wird automatisch aufgelöst. Bei OneDrive/SharePoint muss
   die Bibliothek auf dem Ziel-PC synchronisiert sein.

Mit **Jetzt installieren** prüft der Installer die Schreibberechtigung, kopiert den Agenten nach
`%LOCALAPPDATA%\KirschkeRDPAgent`, erstellt die Konfiguration, richtet den Autostart beim Anmelden ein und startet
den Agenten sofort. Das funktioniert im Benutzerkontext und benötigt keine Administratorrechte. Der Installer
kann bei Bedarf wiederholt werden, etwa um den Agenten zu aktualisieren oder den Statusordner zu ändern.

Für automatisierte Rollouts bleibt eine unbeaufsichtigte Installation möglich:

```powershell
.\Install-Agent.ps1 -NoUi -WorkstationId "WS-001" -StatusDirectory "C:\Pfad\zum\RDP-Portal\remote\agenten-status"
```

## 4. Ergebnis prüfen

Nach etwa 30–60 Sekunden im Portal **Einstellungen** öffnen. Bei der Agent-Statusanzeige
muss die Maschine gezählt werden. Der Installer prüft bereits beim Start, ob der Agent
eine neue Online-Statusdatei schreibt. Bei OneDrive kommt die Synchronisationszeit hinzu.
Der gebaute Agent läuft ohne Konsolenfenster; die Diagnose erfolgt über Statusdatei und Log.

Die Statusdatei heißt `<Maschinen-ID>.json` und liegt direkt im gewählten Statusordner. Bei Problemen zuerst
`%LOCALAPPDATA%\KirschkeRDPAgent\agent.log` und den OneDrive-Synchronisationsstatus prüfen.

## Deinstallieren

Das entfernt nur den Autostart; Konfiguration und Log bleiben zur Diagnose erhalten:

```powershell
.\Kirschke-RDP-Agent-Setup.exe --uninstall
```

## Wichtige Grenze des Pilotbetriebs

Der Autostart läuft im Kontext des angemeldeten Benutzers. Meldet sich dieser vollständig ab, beendet Windows auch den
Agenten. Ein dauerhafter Windows-Dienst wäre möglich, benötigt ohne AD/verwaltetes Dienstkonto aber eine bewusst
eingerichtete Berechtigung auf den gemeinsamen Speicher. Das ist deshalb nicht automatisch aktiviert.
