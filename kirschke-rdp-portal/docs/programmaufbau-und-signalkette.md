# Programmaufbau und Signalkette

Stand: 07.10.2026. Schematische Darstellung des aktuellen Pilotbetriebs.
Die Pfeile zeigen die Richtung der Daten oder Anfragen; die Rückantwort läuft
über denselben Kanal zurück. Eine gestartete RDP-Verbindung und eine bestätigte
Windows-Anmeldung sind unterschiedliche Zustände.

```mermaid
flowchart LR
    subgraph Client[Portal-PC]
        UI[PySide6-Oberfläche<br/>Maschinen, Details, Kalender, Logs]
        MW[MainWindow<br/>Aktionen und Statustakt]
        RDP[RDP-Profil und Launcher]
        MSTSC[Windows mstsc.exe]
        POLL[LiveStatusPoller<br/>STATUS/1]
        SCAN[FallbackScanner<br/>JSON lesen]
        CLAIM[SessionClaimReporter<br/>CLAIM/1]
        LOGOFF[SessionControl<br/>LOGOFF/1]
        STORE[LocalStore<br/>Inventar, Reservierungen, Ereignisse]
        PREF[Lokales Benutzerprofil<br/>Einstellungen und Windows Credential Manager]
        UI --> MW
        MW --> RDP --> MSTSC
        MW --> POLL
        MW --> SCAN
        MW --> CLAIM
        MW --> LOGOFF
        MW <--> STORE
        MW <--> PREF
    end

    subgraph Ziel[Zielrechner]
        WIN[Windows RDP-Dienst<br/>Anmeldung und Sitzung]
        PIPE[Agent-Statusserver<br/>geschützte Named Pipe]
        AGENT[WorkstationAgent<br/>WTS-Sitzungen und Status]
        CLAIMS[Agent-Speicher<br/>Aufschaltmeldungen und Reservierungen]
        STATUS[Lokaler Statusordner<br/>Agent-Snapshot JSON]
        MSTSC -- RDP und Windows-Anmeldung --> WIN
        WIN -- Sitzungsdaten per WTS --> AGENT
        PIPE <--> AGENT
        PIPE <--> CLAIMS
        AGENT <--> CLAIMS
        AGENT -- Snapshot atomar schreiben --> STATUS
    end

    subgraph Netzwerk[Netzwerkordner per SMB]
        FALLBACK[Statusfreigabe je Agent<br/>RDP-Status: nur Lesen für Portal]
        INVENTORY[Optionales gemeinsames Inventar<br/>portal-state.json]
        EVENTS[Optionales gemeinsames Protokoll<br/>portal-events.jsonl]
    end

    POLL -- STATUS/1 --> PIPE
    PIPE -- frischer Snapshot --> POLL
    CLAIM -- CLAIM/1: Portal-Aufschaltung --> PIPE
    LOGOFF -- LOGOFF/1 --> PIPE
    PIPE -- Prüfung und Ergebnis --> LOGOFF
    STATUS -- Freigabe --> FALLBACK
    FALLBACK -- Datei-Fallback --> SCAN
    STORE <--> INVENTORY
    STORE -- Ereignisse anhängen --> EVENTS
    MW -- RESERVE/1: Reservierungen --> PIPE
```

**Einordnung der Ablagen:** Ohne gemeinsames Inventar verwendet `LocalStore`
`state/portal-state.json` neben der Portal-EXE. Persönliche Einstellungen und
die Pfade der Freigaben liegen unter `%LOCALAPPDATA%\KirschkeRDPPortal\`;
Anmeldedaten für Freigaben liegen im Windows Credential Manager. Ein
eigenständiger Protokollordner ist optional; sonst liegt das Ereignisprotokoll
bei den Inventardaten. Die Statusfreigabe des Agenten ist für das Portal nur
lesbar. Das Portal schreibt seine Aufschaltmeldungen und Reservierungen über die
Named Pipe an den Agenten, nicht in die Statusfreigabe.

**Signalkette:** Der Agent liest die tatsächlichen Sitzungen über die Windows
Terminal Services API (WTS). Er liefert einen frischen Snapshot über
`STATUS/1` und schreibt zusätzlich eine JSON-Datei für den SMB-Fallback. Das
Portal ordnet die Meldung anhand der Agenten-ID beziehungsweise der eindeutigen
Maschinenzuordnung zu und aktualisiert die Oberfläche. Ein `CLAIM/1` meldet,
wer eine Verbindung über das Portal gestartet hat; diese Meldung allein beweist
weder eine erfolgreiche Anmeldung noch eine Abmeldeberechtigung.

Details zu den Dateien und Ausfällen: [Datenspeicherung](datenspeicherung.md).
