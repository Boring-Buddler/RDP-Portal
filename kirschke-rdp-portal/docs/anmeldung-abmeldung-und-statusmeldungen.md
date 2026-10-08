# Anmeldung, Abmeldung und Statusmeldungen

Stand: 07.10.2026. Das Flussdiagramm zeigt den regulären RDP-Weg und die
Meldungen von Portal und Agent. Die optionale administrative Notfall-Abmeldung
ist als eigener Zweig eingezeichnet.

```mermaid
flowchart TD
    START([Benutzer wählt Maschine und Anmelden als])
    CHECK{Maschine nutzbar und<br/>Warnung oder Reservierung bestätigt?}
    PROFILE[RDP-Ziel und Konto prüfen;<br/>temporäre RDP-Datei erzeugen]
    LAUNCH[mstsc.exe starten]
    LAUNCHOK{Start gelungen?}
    FAIL[Portal protokolliert Startfehler]
    LOGSTART[Portal protokolliert Verbindungsstart]
    CLAIM[Portal sendet CLAIM/1 an Agenten;<br/>bei Störung später erneut]
    WINDOWS{Windows-RDP-Anmeldung<br/>gelingt?}
    SESSION[Windows führt die Sitzung;<br/>Agent liest sie über WTS]
    NOSESSION[Keine bestätigte Sitzung;<br/>ungebundene Meldung läuft ab]

    START --> CHECK
    CHECK -- Nein --> STOP([Kein Verbindungsstart])
    CHECK -- Ja --> PROFILE --> LAUNCH --> LAUNCHOK
    LAUNCHOK -- Nein --> FAIL --> STOP
    LAUNCHOK -- Ja --> LOGSTART --> WINDOWS
    LOGSTART --> CLAIM
    WINDOWS -- Nein oder Abbruch --> NOSESSION
    WINDOWS -- Ja --> SESSION

    subgraph STATUS[Agentenmeldung und Portal-Anzeige]
        WTS[Agent erfasst Sitzungen und bindet<br/>Aufschaltmeldung an Konto und RDP-Client]
        SNAP[Agent erzeugt Status-Snapshot<br/>mit Sitzungen, Meldungen, Reservierungen]
        PIPE[Portal fragt STATUS/1<br/>über geschützte Named Pipe ab]
        FILE[Agent schreibt Snapshot-JSON<br/>in lokalen Statusordner]
        SHARE[SMB-Freigabe RDP-Status<br/>Portal liest Datei-Fallback]
        VIEW[Portal prüft Agenten-Zuordnung und Alter;<br/>aktualisiert Karten und Details]
        WTS --> SNAP
        SNAP --> PIPE --> VIEW
        SNAP --> FILE --> SHARE --> VIEW
    end

    SESSION --> WTS
    CLAIM -. Meldung wird beim nächsten Snapshot zugeordnet .-> WTS

    subgraph ABMELDEN[Abmelden oder RDP-Fenster schließen]
        CHOICE{Benutzeraktion?}
        CLOSE[Lokales RDP-Fenster schließen;<br/>Portal protokolliert Trennung]
        SELECT[Abmelden wählen und<br/>Sitzung bestätigen]
        FRESH[Portal holt frischen STATUS/1;<br/>prüft ID, Konto und Anmeldezeit]
        OWNER{Eigene RDP-Sitzung<br/>oder Admin-Notfallweg?}
        REQUEST[Portal sendet LOGOFF/1;<br/>Live-Polling für Maschine pausiert]
        VERIFY[Agent prüft Frische, Sitzung und<br/>RDP-Client bzw. Windows-Adminrecht]
        APPROVED{Prüfung erfolgreich?}
        WTSOFF[Agent meldet Sitzung über WTS ab<br/>und veröffentlicht neuen Status]
        CONFIRM[Portal prüft Sitzungsende erneut<br/>und aktualisiert die Anzeige]
        REJECT[Abmeldung abgelehnt;<br/>Sitzung bleibt bestehen]
        DISCONNECTED[Windows-Sitzung kann<br/>getrennt bestehen bleiben]
        CHOICE -- Fenster schließen --> CLOSE --> DISCONNECTED
        CHOICE -- Abmelden --> SELECT --> FRESH --> OWNER
        OWNER -- Nein --> REJECT
        OWNER -- Ja --> REQUEST --> VERIFY --> APPROVED
        APPROVED -- Nein --> REJECT
        APPROVED -- Ja --> WTSOFF --> CONFIRM
    end

    SESSION --> CHOICE
    WTSOFF --> WTS

    subgraph ABLAGE[Netzwerkordner und lokale Ablagen]
        PORTALDATA[Portal lädt und speichert<br/>Maschinen und Reservierungen]
        INVENTORY[Optionales gemeinsames SMB-Inventar<br/>portal-state.json und Reservierungen]
        EVENTS[Optionaler SMB-Protokollordner<br/>portal-events.jsonl]
        LOCAL[Ohne Inventarfreigabe:<br/>state neben Portal-EXE]
        PREF[Je Portal-PC lokal:<br/>Einstellungen und Freigabepfade]
        AGENTDATA[Je Agent lokal:<br/>Meldungen und Reservierungen]
    end

    LOGSTART --> EVENTS
    FAIL --> EVENTS
    CLOSE --> EVENTS
    PORTALDATA --> INVENTORY
    PORTALDATA --> LOCAL
    PORTALDATA -. Maschinen und Reservierungen .-> START
    CLAIM --> AGENTDATA
    SNAP --> AGENTDATA
    START --> PREF
```

Die Pfeile zu `portal-events.jsonl` zeigen den optionalen gemeinsamen
Protokollordner. Ohne dessen Einrichtung schreibt das Portal das Protokoll bei
seinen Inventardaten. Die Verzweigung zu `state` gilt, wenn kein gemeinsames
Inventar konfiguriert ist. Reservierungen werden im Portal-Inventar gespeichert
und zusätzlich per `RESERVE/1` an den jeweiligen Agenten übertragen; dessen
Snapshot verteilt sie an andere Portale. Die Statusdatei unter `RDP-Status` ist
ein Lese-Fallback, keine Befehlswarteschlange.

Ein erfolgreicher `mstsc.exe`-Start ist nur ein gestarteter Verbindungsversuch.
Das Portal erkennt eine tatsächliche Sitzung erst über Windows und den
Agentenstatus. Das bloße Schließen des RDP-Fensters beendet die Windows-Sitzung
nicht zuverlässig. Für eine echte Abmeldung verlangt der Agent eine aktuelle,
eindeutig identifizierte Sitzung und prüft die Berechtigung selbst. Bleibt die
Antwort auf `LOGOFF/1` aus, fragt das Portal den Status erneut ab, bevor es das
Ergebnis meldet.
