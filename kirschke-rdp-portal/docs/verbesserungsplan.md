# Verbesserungs- und Ausbauplan

Stand: 08.10.2026. Grundlage: aktueller Arbeitsstand mit Portal 0.9.3 und
Agent 1.7.3. Dieser Plan beschreibt vorgeschlagene Arbeiten; er ist keine
Freigabe zur Umsetzung aller Pakete. Aufwand und Reihenfolge sind Einschätzungen
für einen Entwickler mit Kenntnis des Projekts, keine Terminzusagen.

## Ziel

Das Portal soll im täglichen Mehrbenutzerbetrieb verlässliche Buchungen und
Sitzungsinformationen liefern, bei Netzwerkfehlern bedienbar bleiben und sich
einfach betreuen lassen. Ich würde die vorhandene Architektur aus Windows-RDP,
Agenten und SMB-Freigaben zunächst weiterentwickeln. Ein zusätzlicher zentraler
Server sollte erst aus einem konkreten Bedarf entstehen.

## Befunde aus dem aktuellen Stand

| Befund | Folge und Ansatzpunkt | Nachweis |
| --- | --- | --- |
| Der Agent ersetzt die ganze Reservierungsliste einer Maschine nach „last write wins“. | Gleichzeitige Änderungen können eine Buchung verdrängen; Revisionen und Konfliktprüfung ergänzen. | [reservation_store.py](../workstation_agent/reservation_store.py) |
| Fehlgeschlagene Reservierungsübertragungen werden einmal gemeldet und nicht automatisch wiederholt. Agentenlisten ersetzen anschließend den Portalstand je Maschine. | Eine lokale Buchung wird nicht allein durch Wiederkehr des Agenten verteilt und kann durch einen älteren Agentenstand aus der Anzeige verschwinden. | [reservation_sync.py](../portal_app/services/reservation_sync.py), [MainWindow](../portal_app/ui/main_window.py) |
| Reservierungen können beim Agenten als erfolgreich übernommen gelten, obwohl das Schreiben auf die Platte fehlgeschlagen ist. | Nach einem Agentenneustart kann die Buchung fehlen; dauerhafte Speicherung ausdrücklich quittieren. | [ReservationStore.replace](../workstation_agent/reservation_store.py) |
| Hintergrundjobs existieren bereits, einzelne Pipe- und Speicherzugriffe laufen aber weiterhin im UI-Thread. | Bei langsamen Freigaben können unter anderem Übernahme, Aktualisierung, Speichern und Buchungen das Fenster anhalten. | [session_takeover_dialog.py](../portal_app/ui/widgets/session_takeover_dialog.py), [MainWindow](../portal_app/ui/main_window.py) |
| Portalereignisse und beobachtete Agenten-Sitzungsverläufe sind getrennte Datenwege. | Eine vollständige, gemeinsame Zeitleiste fehlt; ein Startversuch muss von einer bestätigten Sitzung unterscheidbar bleiben. | [session_history.py](../workstation_agent/session_history.py), [README](../README.md#known-limitations-phase-1) |
| Der Portal-Adminzugang verwendet ein gemeinsames Passwort; ein Lesekonto-Kennwort kann im Auslieferungspaket stehen. | Für den Regelbetrieb Zugänge und Rotation planen; Portal-Freischaltung und tatsächliche Windows-/SMB-Rechte getrennt behandeln. | [Security Notes](../README.md#security-notes) |
| Der Statusserver bearbeitet nur einen Client gleichzeitig. | Eine Abmeldung kann andere Portale zeitweise von Statusantworten ausschließen; zunächst messen und als „Vorgang läuft“ darstellen. | [status_server.py](../workstation_agent/status_server.py) |
| Paketmetadaten nennen 0.2.12, Laufzeit und README 0.9.3. Ältere Dokumente und Features-Listen beschreiben teilweise überholte Zustände. | Eine aktuelle, eindeutige Betriebs- und Releasebeschreibung schaffen. | [pyproject.toml](../pyproject.toml), [shared/version.py](../shared/version.py), [README](../README.md) |

Diese Befunde stammen aus dem Lesen von Code und Dokumentation. Ein neuer
vollständiger Testlauf, eine Lastmessung und eine praktische Windows-Abnahme
wurden für die Planung nicht durchgeführt. Historische Testzahlen und
Typprüfungsbefunde werden deshalb nicht als aktueller Prüfstand übernommen.

## Reihenfolge

Aufwand: **S** = kleines Paket, **M** = mehrere zusammenhängende Änderungen,
**L** = Änderung über Portal, Agent und Protokoll mit Migration und Windows-Abnahme.

| Reihenfolge | Paket | Priorität | Aufwand | Ergebnis |
| --- | --- | --- | --- | --- |
| 1 | A: Aktuellen Stand und Release-Basis vereinheitlichen | Hoch | S–M | Eine belastbare Ausgangsbasis |
| 2 | B: Reservierungen zuverlässig synchronisieren | Hoch | L | Keine still verlorenen Buchungen |
| 3 | C: Netzwerk und Speicherung vollständig aus dem UI-Thread lösen | Hoch | M–L | Bedienung auch bei Ausfällen |
| 4 | D: Zustand und Fehler verständlich erklären | Hoch | M | Weniger Fehlbedienung und Supportaufwand |
| 5 | E: Gemeinsame Sitzungshistorie vervollständigen | Mittel | M–L | Nachvollziehbare tatsächliche Abläufe |
| 6 | F: Sicherung und Wiederherstellung ergänzen | Hoch vor Regelbetrieb | M | Inventar nach Fehlern wiederherstellbar |
| 7 | G: Zugänge und Vertrauen weiter absichern | Hoch vor breitem Rollout | L | Verwaltbare Zugangsdaten und Zertifikate |
| 8 | H: Auslieferung, Updates und Kompatibilität | Hoch vor breitem Rollout | L | Kontrollierte Versionswechsel |
| 9 | I: Komfortfunktionen | Mittel | Je Funktion S–L | Spürbarer Nutzen im Büroalltag |
| Begleitend | J: Verantwortlichkeiten im Code klarer trennen | Mittel | M je Teil | Änderungen leichter prüfen und warten |

## Etappe 1: Verlässlicher täglicher Betrieb

### A – Aktuellen Stand vereinheitlichen

- Versionsquelle für Paketmetadaten, Laufzeit, Setup und Dokumentation abstimmen.
- README-Features und Betriebsanleitungen auf den tatsächlich aktiven Stand bringen.
  Historische Prüfberichte als solche markieren und eine aktuelle Abnahmeliste führen.
- Python-, Laufzeit- und Build-Abhängigkeiten für Auslieferungen reproduzierbar
  festhalten; ungenutzte Phase-2-Abhängigkeiten auf tatsächliche Verwendung prüfen.
- Aktuellen Ruff-, Pytest- und Mypy-Stand erfassen. Für bekannte Typbefunde eine
  überprüfbare Baseline führen und neue Befunde verhindern.

**Abnahme:** Laufzeit, Installationsdialog und Paket melden die erwartete Version.
Ein sauberer Windows-Build erzeugt startbare Pakete; die dokumentierten Checks
lassen sich auf einem zweiten Rechner nachvollziehen.

### B – Reservierungssynchronisierung überarbeiten

- Je Maschine eine Revision einführen. Änderungen müssen die gelesene Revision
  mitbringen; der Agent lehnt veraltete Änderungen mit verständlichem Konflikt ab.
- Der Agent prüft Zeitüberschneidungen innerhalb derselben atomaren Änderung.
  Jede Operation bekommt eine ID, damit Wiederholungen keine Doppelbuchungen erzeugen.
- Ausstehende Reservierungsänderungen lokal dauerhaft vormerken und im Hintergrund
  erneut zustellen. Alte Snapshots dürfen offene lokale Änderungen nicht verdrängen.
- Anzeigen: „Übertragung ausstehend“, „vom Agenten dauerhaft bestätigt“ oder
  „Konflikt – neu laden“. Erst erfolgreiche Persistenz erhält die dauerhafte Quittung.
- Für Maschinen mit Agenten den Agenten als maßgeblichen Buchungsstand festlegen;
  das gemeinsame Inventar enthält eine nachvollziehbare Kopie. Buchungen ohne
  geeigneten Agenten ausdrücklich als lokal beziehungsweise nur über das Inventar
  geteilt kennzeichnen. Keinen stillen Wechsel zwischen beiden Zuständigkeiten zulassen.
- Protokollfähigkeiten aushandeln. Alte Agenten bleiben lesbar; das Portal benennt
  deren schwächere Buchungsgarantien und verlangt für den neuen Weg ein Update.

**Abnahme:** Zwei Portale buchen dieselbe Maschine gleichzeitig. Unabhängige
Änderungen bleiben erhalten oder erzeugen einen sichtbaren Konflikt;
Überschneidungen werden abgewiesen. Netzunterbrechung, verlorene Antwort,
Portalneustart und Agentenneustart erzeugen weder verlorene noch doppelte Buchungen.
Eine volle oder schreibgeschützte Agentenablage wird nicht als dauerhaft gespeichert
quittiert. Reservierungen bleiben organisatorische Hinweise und erteilen keine
Windows-Rechte.

### C – Alle blockierenden Zugriffe im Hintergrund ausführen

- Reservierungsübertragung, Übernahmeprüfung, Inventarlesen, Ereignislesen und
  Speichern als Hintergrundjobs ausführen; auch Start und manuelles Aktualisieren prüfen.
- Jobs begrenzen, Fortschritt und Abbruch anbieten. Ergebnisse nach Zielwechsel
  oder Schließen eines Dialogs verwerfen; keine parallelen Schreibvorgänge derselben
  Portalinstanz zulassen.
- Abbruch eines bereits gestarteten Schreibens oder Abmeldens als ungewisses
  Ergebnis behandeln und anschließend prüfen. Abmeldebefehle nicht automatisch
  nachträglich erneut ausführen.

**Abnahme:** Bei einer künstlich langsamen oder getrennten SMB-Freigabe bleiben
Navigation und Dialoge bedienbar. Übernahmeprüfung und Buchung frieren das Fenster
nicht ein. Verspätete Antworten verändern keine inzwischen andere Maschine.

### D – Diagnose und Sitzungszustände verbessern

- Eine gemeinsame Diagnoseansicht zeigt RDP-Ziel, Agentenziel, Statusfreigabe,
  Inventar- und Protokollordner mit getrennten Prüfergebnissen.
- Zustände klar benennen: „Start angefordert“, „Sitzung vom Agenten bestätigt“,
  „getrennte Sitzung“, „Abmeldung läuft“, „Status veraltet“ und „Status unbekannt“.
- Fehler mit einer konkreten nächsten Handlung anzeigen: etwa Lesekonto prüfen,
  Agent zuordnen, Netzwerkordner verbinden oder Buchung nach Konflikt neu laden.
- Übernahmebestätigung an passenden Agenten, Konto und tatsächlich gemeldeten
  RDP-Client binden; ein gleicher Kontoname allein genügt für diese Anzeige nicht.
- Supportbericht mit Versionen, Pfaden, Quellen und Fehlercodes exportieren.
  Kennwörter und Tokens ausschließen; interne Namen vor Export optional maskieren.

**Abnahme:** RDP erreichbar/Agent unerreichbar, Zugriff verweigert, falsche
Agentenzuordnung und veraltete Statusdatei sind sichtbar unterscheidbar.
Die Oberfläche behauptet nach einem Prozessstart keine erfolgreiche Anmeldung.

## Etappe 2: Nachvollziehbarkeit und Wiederherstellung

### E – Gemeinsame Sitzungshistorie

- Portalaktionen und vom Agenten beobachtete Zustandswechsel in einer Zeitleiste
  zusammenführen. Quelle und Beobachtungszeit immer mitführen.
- Verbindungsstart, bestätigte Anmeldung, Trennung, Wiederverbindung und bestätigte
  Abmeldung unterscheiden. Auch die normale eigene Abmeldung protokollieren.
- Agentenereignisse mit stabiler Ereignis-ID, Agentenkennung und Reihenfolge
  abrufen. Mehrere Portale dürfen dasselbe Ereignis nicht mehrfach eintragen.
- Nach Netzunterbrechungen nachladen; einen begrenzten Verlauf und erkennbare
  Lücken vorsehen. Polling-Beobachtungen nicht als lückenlose Windows-Ereigniserfassung
  ausgeben. Für exakte Windows-Ereignisse wäre eine zusätzliche Quelle zu integrieren.
- Aufbewahrung und Export konfigurierbar machen. Ein beschreibbares SMB-Protokoll
  ausdrücklich nicht als manipulationssicheres Audit bezeichnen.

**Abnahme:** Eine Sitzung wird über zwei Portale beobachtet und erscheint mit
jedem tatsächlich erfassten Übergang genau einmal. Ein Ereignis nach Offlinezeit
wird nachgeliefert; eine nicht mehr rekonstruierbare Lücke ist sichtbar.

### F – Sicherung und Wiederherstellung

- Versionierte Sicherungen des Inventars und der Konfiguration anlegen;
  Sicherung konsistent unter der vorhandenen Schreibsperre erzeugen.
- Aufbewahrung begrenzen und letzte erfolgreiche Sicherung anzeigen.
- Wiederherstellung mit Vorschau, Validierung und Sicherung des aktuellen Stands
  anbieten. Gemeinsame Wiederherstellung gegen parallele Schreiber absichern.
- Die vorhandene Notbetriebskopie von einer administrativen Sicherung unterscheiden.
  Lokale Notbetriebänderungen nicht automatisch in ein wieder erreichbares Inventar
  zurückschreiben.

**Abnahme:** Eine beschädigte Inventardatei lässt sich in einer getrennten
Testumgebung wiederherstellen. Andere aktive Portale werden aktualisiert;
Zugangsdaten gelangen nicht in den Export.

## Etappe 3: Verwalteter Rollout

### G – Zugänge und Vertrauen

- Für reguläre Auslieferungen ein eingebettetes, gemeinsam verwendetes Lesekonto-
  Kennwort vermeiden. Einrichtungsassistent und Credential Manager verwenden;
  Zugangsdaten je Freigabeserver speichern und einen bewussten Rotationsweg anbieten.
  Windows ordnet gespeicherte Zugangsdaten dem Benutzerkontext zu:
  [Microsoft: CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew).
- Das vorhandene gemeinsame Portal-Adminpasswort als Betriebsentscheidung behandeln.
  Für verwaltete Rechner personenbezogene Windows-Gruppenrechte vorsehen;
  für Arbeitsgruppen einen ausdrücklich konfigurierten lokalen Weg erhalten.
- Zugriffsrechte an Inventar und Protokoll separat prüfen. Eine Rollenanzeige im
  Portal allein begrenzt keine direkten Schreibzugriffe auf die Freigabe.
- Die Agenten-Autorisierung bei jeder Erweiterung erhalten. Die Named Pipe prüft
  den tatsächlich authentifizierten Windows-Kontext; eine gemeldete Person ersetzt
  diesen Nachweis nicht. [Microsoft: Named-Pipe-Clientkontext](https://learn.microsoft.com/en-us/windows/win32/ipc/impersonating-a-named-pipe-client).
- Vertrauenswürdige RDP-Serverzertifikate und deren Erneuerung für die reale
  Umgebung planen. Bestehende Serveridentitäts-Ausnahmen sichtbar machen.
  Den vorhandenen [RDP-Signaturplan](rdp-signatur-plan.md) dafür gesondert prüfen:
  Dateisignatur, Serverzertifikat und signierte Programmdatei sind verschiedene Aufgaben.

**Abnahme:** Eine neue Installation benötigt kein gemeinsames Kennwort in der EXE.
Rotation funktioniert ohne Quellcodeänderung. Bestehende SMB-Verbindungen anderer
Anwendungen bleiben erhalten; Admin-Freischaltung allein erlaubt keine fremde Abmeldung.

### H – Auslieferung und Updates

- Windows-CI für Tests, Linting, Typbaseline und Paketbau einrichten; Artefakte mit
  Versionsmanifest, Abhängigkeitsständen und Prüfsummen versehen.
- EXE- und Setup-Signaturen beim Build erzeugen und danach prüfen. Der Signierschlüssel
  gehört in die Releaseumgebung. SignTool unterstützt Signatur, Zeitstempel und
  Verifikation. [Microsoft: SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool).
- Im Portal eine Versions- und Fähigkeitenübersicht der Agenten anzeigen.
  Protokollversion und Funktionen prüfen, statt ausschließlich Versionsnummern zu vergleichen.
- Einen einheitlichen unterstützten Installationsweg dokumentieren; den alten
  `Install-Agent.cmd`-Weg klar als Altweg kennzeichnen und später kontrolliert ablösen.
- Updates zunächst als bewusst gestarteten, geprüften Installationsvorgang umsetzen:
  Pilotmaschine, Konfiguration sichern, Update, Statusprüfung, bei Fehlschlag Rollback.
  Laufende Windows-Sitzungen erhalten und Wartungszustände anzeigen.

**Abnahme:** Manipulierte Updatepakete werden abgewiesen. Ein Update behält
Maschinen-ID, Freigaben und lokale Konfiguration. Ein fehlgeschlagenes Update ist
rückgängig machbar; die getestete Kombination aus Portal und Agent ist dokumentiert.
Eine Signatur allein wird nicht als garantierte Freigabe durch jede Windows-Richtlinie dargestellt.

## Etappe 4: Neue Funktionen mit täglichem Nutzen

| Funktion | Vorgeschlagene Umsetzung | Abnahme | Rang |
| --- | --- | --- | --- |
| „Benachrichtige mich, wenn frei“ | Maschine beobachten und bei einem frisch bestätigten Wechsel auf verfügbar einmal benachrichtigen. | Veralteter Status oder Agentenausfall löst keine Frei-Meldung aus; keine Meldungsflut bei kurzen Wechseln. | 1 |
| Wiederkehrende Reservierungen und Erinnerungen | Serien mit Enddatum, Ausnahmen und Vorschau aller Konflikte; Beginn/Ende lokal erinnern. | Sommerzeit, Serienänderung und parallele Buchung sind korrekt; abhängig von Paket B. | 2 |
| Erwartetes Ende für „Berechnung läuft“ | Den bereits vorhandenen Ablaufzeitpunkt im Dialog bedienbar machen und Erinnerung anbieten. | Ablauf erinnert den Verantwortlichen; er meldet niemanden automatisch ab und erklärt eine unbekannte Sitzung nicht für frei. | 3 |
| Profile für Anzeige und Umleitungen | Benannte Profile für Büro, VPN und mehrere Monitore; je Maschine auswählbar. | Die erzeugte RDP-Datei entspricht dem Profil; bestehende Einstellungen migrieren korrekt. | 4 |
| Geführter Inventarimport | CSV/JSON vorab prüfen, Dubletten und Agentenzuordnung in einer Vorschau zeigen. | Erst nach Bestätigung speichern; ungültige Zeilen überschreiben keine Maschinen. | 5 |
| Wake-on-LAN | MAC-Adresse und bewusster Aufweckknopf; danach Erreichbarkeit getrennt prüfen. | Ein gesendetes Paket gilt nicht als erfolgreicher Start; Netzsegment, VPN und Zielhardware werden vorab praktisch geprüft. | Optional |
| Nutzungsübersicht | Aus der Sitzungshistorie Nutzung je Maschine und Zeitraum auswerten, Beobachtungslücken ausweisen. | Gemessene Zeit und unbekannte Zeit sind getrennt; abhängig von Paket E. | Optional |

Die Benachrichtigungen funktionieren zunächst nur bei laufendem Portal.
Benachrichtigungen nach dem Schließen würden einen weiteren Hintergrundprozess
oder einen zentralen Dienst erfordern und gehören in ein eigenes Paket.

## Begleitend: J – Wartbarkeit

- Verbindungsablauf, Reservierungssynchronisierung und Speicherjobs schrittweise
  aus `MainWindow` in klar begrenzte Verantwortlichkeiten verschieben.
- Agenten-Snapshots, Fehler und Quittungen an den Schnittstellen stärker typisieren.
  Bekannte Typbefunde paketweise abbauen.
- Für Persistenz und Protokoll ein Schema mit Version und Migration vorsehen.
  Alte Daten zunächst in einer Kopie migrieren und validieren.
- Den seriellen Agentenkanal mit der tatsächlich erwarteten Anzahl von Portalen
  messen. Erst bei belegten Engpässen Statusantworten und längere Aktionen über
  begrenzte getrennte Worker bedienen; WTS-Zugriffe und Schreiboperationen absichern.

## Abnahme je Etappe

Jedes Paket erhält einen eigenen Feature- oder Fix-Branch, passende Unit- und
Integrationstests sowie aktualisierte README-/Betriebsdokumentation.
Vor dem Merge gelten die Projektprüfungen aus [AGENTS.md](../AGENTS.md):
Ruff sauber, Tests erfolgreich, keine neuen Typbefunde oder unbegründeten Ignores,
menschliches Review und dokumentierte visuelle Prüfung bei UI-Änderungen.

Für die praktische Abnahme mindestens zwei Portal-PCs und einen getrennten
Windows-Zielrechner verwenden. Prüfen: gleiche und unterschiedliche Konten,
RDP- und Konsolensitzung, getrennter Zustand, falsche Zugangsdaten, parallele
Buchungen, Netzwerkverlust, schreibgeschützte Ablage sowie Portal-/Agentenneustart.
UI zusätzlich in Hell/Dunkel, mit größerer Schrift, hoher DPI und Tastatur prüfen.

**Empfohlenes erstes Umsetzungspaket:** A, B und C abschließen und die für diese
Abläufe benötigten Zustandsanzeigen aus D ergänzen. Danach E und F, anschließend
G und H für einen breiteren Rollout. Die erste neue Komfortfunktion wäre
„Benachrichtige mich, wenn frei“. Cloud-Anbindung, ein neuer zentraler Server
und allgemeine Remote-Befehle sind spätere Architekturentscheidungen bei
nachgewiesenem Bedarf.
