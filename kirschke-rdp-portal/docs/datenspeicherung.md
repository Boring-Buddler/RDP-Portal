# Wo das Portal seine Daten speichert

Für: Betreuer des Testbetriebs. Beantwortet die zwei Fragen, die im Mehrbenutzerbetrieb
zählen — was teilen sich alle, und was hat jeder für sich.

## Die kurze Antwort

Es gibt **zwei** Ablagen, und die Trennung ist Absicht.

| | Gemeinsam | Persönlich |
|---|---|---|
| Ort | `<Ordner der Portal-EXE>\state\` | `%LOCALAPPDATA%\KirschkeRDPPortal\` |
| Gilt für | alle, die dieselbe EXE starten | einen Windows-Benutzer auf einem PC |
| Inhalt | Maschinen, Reservierungen, Ereignisprotokoll | Kontowahl, Design, Intervall, eigene Konten |
| Bei Parallelbetrieb | zusammengeführt, nie blind überschrieben | von niemand anderem angefasst |

## Gemeinsame Ablage

Alles im Ordner `state` neben der Portal-EXE ([`default_portal_directory`](../shared/agent_paths.py)):

| Datei | Inhalt |
|---|---|
| `portal-state.json` | Maschinen und Reservierungen |
| `portal-events.jsonl` | Ereignisprotokoll, fortlaufend angehängt, rotiert bei 4 MB — **verschiebbar**, siehe unten |
| `portal-directory-users.json` | Cache der wählbaren AD-/Entra-Konten |
| `portal-state.lock` | Schreibsperre, kurzlebig |

### Wird bei gleichzeitiger Nutzung etwas überschrieben?

**Nein.** `LocalStore.save()` ([local_store.py](../portal_app/services/local_store.py)) macht bei
jedem Schreibvorgang Folgendes:

1. Schreibsperre auf die Lock-Datei nehmen.
2. Den Stand auf der Platte **neu einlesen** — er kann sich seit dem Laden geändert haben.
3. **Drei-Wege-Merge pro Datensatz** gegen die Baseline, also gegen den Stand, den dieses
   Portal zuletzt gesehen hat.
4. Atomar schreiben (erst in eine Temp-Datei, dann ersetzen).

Daraus folgt:

* Zwei Leute ändern **verschiedene** Maschinen oder Buchungen → beide Änderungen bleiben erhalten.
* Zwei Leute ändern **denselben** Datensatz → `StoreConflictError`, im Portal als
  „Paralleländerung erkannt“. Es wird **nichts** überschrieben; die zweite Person aktualisiert
  und macht ihre Änderung erneut.
* Eine reservierte Maschine wird gelöscht, während jemand bucht → ebenfalls Konflikt, kein
  verwaister Eintrag.

Zusätzlich gleicht jedes Portal alle 5 Sekunden ab, sobald sich die Dateien verändert haben
(`_sync_shared_store`), sodass fremde Änderungen von selbst erscheinen.

### Die Einschränkung, die man kennen muss

Der Ordner `state` liegt **neben der EXE**. Gemeinsam ist er nur, wenn alle dieselbe Kopie
starten — etwa von einem Netzlaufwerk oder aus einem SharePoint-synchronisierten Ordner.
Hat jeder seine eigene lokale Kopie, hat auch jeder seinen eigenen „gemeinsamen“ Stand, und
die Verteilung hängt allein an der Synchronisierung.

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
| `portal-preferences.json` | Kontowahl je Maschine, Design (hell/dunkel/System), Statusintervall, eigene Windows-Konten, Identität |
| `storage-config.json` | Agent-Statusordner (auch je Maschine) und der gemeinsame Protokollordner |
| `logs\portal.log` | Protokoll, rotiert bei 5 MB |
| `lokal\` | Notablage, falls der gemeinsame Ordner nicht beschreibbar ist |

Diese Datei wird von keinem anderen Portal gelesen oder geschrieben. Zwei Personen am selben
Portal, aber an verschiedenen PCs, sehen dieselben Maschinen und verschiedene Kontowahlen —
so ist es gemeint.

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
