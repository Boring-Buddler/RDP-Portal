# Wo das Portal seine Daten speichert

Für: Betreuer des Testbetriebs. Beantwortet die zwei Fragen, die im Mehrbenutzerbetrieb
zählen — was teilen sich alle, und was hat jeder für sich.

## Die kurze Antwort

Es gibt **zwei** Ablagen, und die Trennung ist Absicht. Gemeinsame Daten laufen
ausschließlich über das Netzwerk; OneDrive- und SharePoint-Ordner lehnt das
Portal überall ab ([sync_guard.py](../shared/sync_guard.py)).

| | Gemeinsam | Persönlich |
|---|---|---|
| Ort | eingetragene Netzwerkfreigabe (**Admin → Gemeinsames Inventar**), sonst `<Ordner der Portal-EXE>\state\` | `%LOCALAPPDATA%\KirschkeRDPPortal\` |
| Gilt für | alle Portale mit derselben Freigabe | einen Windows-Benutzer auf einem PC |
| Inhalt | Maschinen, Reservierungen, Ereignisprotokoll | Kontowahl, Design, Intervall, eigene Konten |
| Bei Parallelbetrieb | zusammengeführt, nie blind überschrieben | von niemand anderem angefasst |

## Gemeinsame Ablage

Alles auf der eingetragenen Freigabe des gemeinsamen Inventars – ohne Eintrag im
Ordner `state` neben der Portal-EXE ([`default_portal_directory`](../shared/agent_paths.py)).
Liegt die EXE selbst in einem OneDrive- oder SharePoint-Ordner, weicht der Stand
nach `%LOCALAPPDATA%\KirschkeRDPPortal\daten` aus:

| Datei | Inhalt |
|---|---|
| `portal-state.json` | Maschinen und Reservierungen |
| `portal-events.jsonl` | Ereignisprotokoll, fortlaufend angehängt, rotiert bei 4 MB — **verschiebbar**, siehe unten |
| `portal-directory-users.json` | Cache der wählbaren AD-/Entra-Konten |
| `portal-state.lock` | Schreibsperre, kurzlebig |

### Wird bei gleichzeitiger Nutzung etwas überschrieben?

**Nein.** `LocalStore.save()` ([local_store.py](../portal_app/services/local_store.py)) macht bei
jedem Schreibvorgang Folgendes:

1. Schreibsperre auf die Lock-Datei nehmen. Das ist eine Byte-Sperre, die der SMB-Server
   für alle Clients durchsetzt – sie gilt also auch zwischen verschiedenen PCs.
2. Den Stand auf der Platte **neu einlesen** — er kann sich seit dem Laden geändert haben.
3. **Drei-Wege-Merge pro Datensatz** gegen die Baseline, also gegen den Stand, den dieses
   Portal zuletzt gesehen hat.
4. Atomar schreiben (erst in eine Temp-Datei, dann ersetzen). Hält ein anderer PC die Datei
   gerade zum Lesen offen, wird das Ersetzen bis zu 2 s wiederholt.

Daraus folgt:

* Zwei Leute ändern **verschiedene** Maschinen oder Buchungen → beide Änderungen bleiben erhalten.
* Zwei Leute ändern **denselben** Datensatz → `StoreConflictError`, im Portal als
  „Paralleländerung erkannt“. Es wird **nichts** überschrieben; die zweite Person aktualisiert
  und macht ihre Änderung erneut.
* Eine reservierte Maschine wird gelöscht, während jemand bucht → ebenfalls Konflikt, kein
  verwaister Eintrag.

Zusätzlich gleicht jedes Portal alle 5 Sekunden ab, sobald sich die Dateien verändert haben
(`_sync_shared_store`), sodass fremde Änderungen von selbst erscheinen. Die Prüfung läuft im
Hintergrund, weil schon ein `stat` auf einer Freigabe hängen kann.

### Wenn die Freigabe nicht erreichbar ist

Dann legt das Portal dort **nichts** an und schreibt dort nichts hin – ein leeres oder
veraltetes Inventar auf der Freigabe ließe bei allen anderen die Maschinen verschwinden.
Es startet im Notbetrieb unter `%LOCALAPPDATA%\KirschkeRDPPortal\lokal` mit der Kopie
`inventar-zuletzt-gelesen.json`, die es bei jedem erfolgreichen Lesen und Schreiben
anlegt. Änderungen im Notbetrieb werden nicht geteilt und später nicht übernommen.

### Ohne gemeinsames Inventar

Der Ordner `state` liegt **neben der EXE**, nach dem Setup also im eigenen Profil. Dann hat
jeder seinen eigenen Stand.

**Reservierungen sind davon unabhängig.** Sie liegen zusätzlich beim Agenten jeder Maschine
([reservation_store.py](../workstation_agent/reservation_store.py)) und reisen mit jedem
Status-Snapshot zu allen Portalen. Das funktioniert auch ohne gemeinsamen Ordner — dort gilt
allerdings *last write wins* pro Maschine, nicht der Merge von oben.

### Gemeinsames Protokoll ohne gemeinsamen Ordner

Wer das Portal über das **Setup** installiert, bekommt es nach
`%LOCALAPPDATA%\Programs\KirschkeRDPPortal` — und weil der gemeinsame Stand neben
der EXE liegt, ist er dort privat. Jeder pflegt dann sein eigenes Maschineninventar.
Reservierungen und Aufschaltmeldungen bleiben trotzdem gemeinsam, weil sie über die Agenten
laufen und nicht über die Datei.

Das Ereignisprotokoll lässt sich als Einziges davon unabhängig teilen:
**Admin → Gemeinsames Protokoll → Protokollordner einrichten**. Ein dort eingetragener
Netzwerkordner nimmt die Ereignisse aller Portale auf; im Reiter *Logs* steht dann, wer wann
welche Maschine verbunden oder abgemeldet hat, quer über alle Beteiligten.

Zwei Dinge dazu:

* Die Freigabe legt das **Agent-Setup** an (Kasten „Gemeinsames Protokoll"), auf genau
  einer Maschine. Sie verwendet dasselbe Konto `PortalLeser`, bekommt aber **nur dort**
  Schreibrecht — der Statusordner derselben Maschine bleibt lesend. Das Portal prüft beim
  Eintragen durch einen echten Schreibversuch, statt den Fehler bis zum ersten Ereignis
  aufzuheben.
* Der Eintrag ist eine Einstellung **dieses PCs** (in `storage-config.json`). Jeder, der
  mitschreiben soll, trägt ihn einmal ein.

Verschoben wird nur das Protokoll; der übrige Stand bleibt, wo er ist.

## Persönliche Ablage

Unter `%LOCALAPPDATA%\KirschkeRDPPortal\` — pro Windows-Benutzer und pro PC:

| Datei | Inhalt |
|---|---|
| `portal-preferences.json` | Maschinenfavoriten, bevorzugte Konten und Kontowahl je Maschine, Karten-/Listenansicht, Design (hell/dunkel/System), Statusintervall, eigene Windows-Konten samt Markierung „gemeinsam genutzt“, Identität |
| `storage-config.json` | Agent-Statusordner (auch je Maschine), der gemeinsame Protokollordner und die Freigabe des gemeinsamen Inventars |
| `inventar-zuletzt-gelesen.json` | Kopie des zuletzt gelesenen gemeinsamen Inventars, für den Notbetrieb |
| `logs\portal.log` | Protokoll, rotiert bei 5 MB |
| `lokal\` | Notablage, falls der gemeinsame Ordner nicht erreichbar oder beschreibbar ist |

Diese Datei wird von keinem anderen Portal gelesen oder geschrieben. Zwei Personen am selben
Portal, aber an verschiedenen PCs, sehen dieselben Maschinen und verschiedene Kontowahlen –
so ist es gemeint.
Auch mit gemeinsamem Inventar bleiben die Favoriten auf diesem PC; sie werden nicht
auf der Freigabe gespeichert.

Was daraus folgt:

* Derselbe Mensch an einem **zweiten PC** startet mit leeren persönlichen Einstellungen.
* Zwei Menschen unter **demselben Windows-Konto** auf einem PC teilen sich diese Datei.
* Ist sie nicht lesbar, holt sich das Portal Design und Intervall ersatzweise aus der
  gemeinsamen Datei, damit der Start nicht scheitert.

## Der Agent

Auf jeder Zielmaschine, neben der Agentenkonfiguration (üblicherweise
`C:\ProgramData\KirschkeRDPAgent\`):

| Datei | Inhalt |
|---|---|
| `agent-reservations.json` | Buchungen dieser Maschine |
| `agent-session-claims.json` | Wer sich unter welchem Windows-Konto aufgeschaltet hat |
| `RDP-Protokoll\portal-events.jsonl` | Das gemeinsame Ereignisprotokoll, falls diese Maschine es beherbergt |
| `<maschine>.json` im Statusordner | Der Snapshot, den der Datei-Fallback liest |

Die Aufschaltmeldungen sind der Grund, warum eine Workstation mit **einem gemeinsamen
Windows-Konto** nicht mehr bei allen als „von dir belegt“ erscheint. Sie sind kein
Rechtenachweis: Der Agent kann nicht prüfen, wer eine Meldung abgesetzt hat, deshalb darf eine
Meldung eine Zuordnung nur *wegnehmen*, nie eine geben
([claim_store.py](../workstation_agent/claim_store.py)).

Weil das Portal **jede** von ihm gestartete Verbindung meldet — und die Meldung wiederholt,
bis der Agent sie hat —, ist ihr Ausbleiben selbst eine Auskunft. Die Karte schreibt dann
„direkt verbunden": Diese Sitzung kam vermutlich über `mstsc` oder am Gerät selbst zustande,
und wer sie hält, ist nur über den Windows-Kontonamen erschlossen. Meldet ein Agent
überhaupt keine Aufschaltungen (Version vor 1.6.0), steht auf der Karte nichts dazu — die
Frage ist dann offen und nicht mit Nein beantwortet.

Eine Meldung trägt die Schreibweise, mit der das Portal verbunden hat; der Agent meldet die
Sitzung als `DOMÄNE\konto`. Zugeordnet wird deshalb über alle Schreibweisen desselben Kontos,
nicht wörtlich. Pro Konto führt der Agent genau eine Meldung, die jüngste.

### Ein Statusordner oder viele?

Der Statusordner ist **je Maschine** einstellbar (Maschinendetails → Fallback einrichten).
Solange eine Maschine keinen eigenen hat, erbt sie den globalen Standard — deshalb kann es
so aussehen, als gäbe es nur einen. Die Maschinendetails unterscheiden beides: Ein geerbter
Pfad steht dort als „Bisheriger Standard".

Mehrere Agenten dürfen sich durchaus eine Freigabe teilen. Zu beachten ist nur, dass
`PortalLeser` ein *lokales* Konto des Rechners ist, auf dem die Freigabe liegt: Für
`\\NB05\RDP-Status` meldet sich `NB05\PortalLeser` an, auch wenn der Ordner zur Maschine
NB13KI gehört.

## Kennwörter

Keines dieser Dateien enthält ein Kennwort. Das Lesekonto der Statusfreigaben liegt im
Windows-Anmeldeinformationsspeicher (Credential Manager), und für die RDP-Anmeldung selbst
fragt Windows.

Dort legt das Portal nur eigene, generische Einträge an:
`KirschkeRDPPortal:Freigabekonto` für das Lesekonto und seit 0.9.4
`KirschkeRDPPortal:Freigabe:<Server>` für ein im Freigabedialog gemerktes Konto.
Einen Eintrag für den ganzen Server (`Domain:target=<Server>`) legt es nicht mehr an:
Den nutzt Windows für jede Anmeldung an diesem Rechner, auch für Remotedesktop.
