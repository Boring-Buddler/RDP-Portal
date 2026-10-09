# Kirschke RDP Workstation Portal

**Version:** Portal 0.9.7 · Agent 1.7.3

**Diagramme:** [Programmaufbau und Signalkette](docs/programmaufbau-und-signalkette.md) ·
[Anmeldung, Abmeldung und Statusmeldungen](docs/anmeldung-abmeldung-und-statusmeldungen.md)

**Ausbauplanung:** [Priorisierter Verbesserungs- und Ausbauplan](docs/verbesserungsplan.md)

## Maschinenübersicht

Der Stern auf einer Maschinenkarte oder in einer Listenzeile markiert einen
persönlichen Favoriten. Mit **☆ Favoriten** links neben dem Standortfilter
werden beim Start nur diese Maschinen angezeigt. Ohne Favoriten lässt sich der
Filter mit einem Klick ausschalten, um alle Maschinen zu sehen. Die
Schaltflächen rechts neben der Suche
wechseln zwischen Karten und kompakter Liste. Ansicht und Favoriten bleiben im
persönlichen Windows-Profil dieses PCs unter
`%LOCALAPPDATA%\KirschkeRDPPortal\portal-preferences.json` gespeichert und
ändern keine gemeinsamen Maschinendaten. Im Dropdown **Anmelden als** markiert der Stern rechts vom
Kontonamen das bevorzugte Konto für diese Maschine; ein Klick darauf wählt es
auch direkt aus. Die bisherige manuelle Kartenreihenfolge bleibt beim Wechsel
der Ansicht erhalten.
Die Maschinenübersicht zeigt einen kompakten Kopf: Zusammenfassung und
**Aktualisieren** stehen neben dem Titel, der Agentstatus direkt über den
Filtern.
Läuft deine eigene Sitzung auf einer Maschine, ohne dass ein Portal-Fenster
offen ist, bleibt der Kartenrand durchgehend blau und das **PC-Symbol wird
orange**. Die fremde Sitzung ohne Fenster bleibt violett/orange gestrichelt.

**„Automatisch“ verbindet mit dem angezeigten Ziel (0.9.7).** Lässt sich der
Name einer Maschine nicht auflösen, etwa an einem anderen Standort ohne
gemeinsames DNS, zeigt die Karte die IP-Adresse – und mit genau dieser wird
jetzt auch verbunden. Bisher stand trotzdem der Name in der `.rdp`-Datei, und
Remotedesktop fand den Computer nicht. Über die IP entfällt das Webkonto; das
Entra-Konto wird dann als `AzureAD\name@firma.de` übergeben, und Windows fragt
das Kennwort ab. Ein Zertifikat, das nur auf den Namen ausgestellt ist, passt
dabei nicht; Windows zeigt deshalb seine Zertifikatswarnung.

**Verbinden ohne Rückfragen des Portals (0.9.6).** Auf einer freien Maschine
startet ein Klick auf **Verbinden** direkt Remotedesktop; Windows fragt dann
höchstens nach dem Kennwort. Entfallen sind die Rückfragen „Serveridentität
bestätigen“ und „IP-Verbindung ohne Webkonto“ sowie die Meldung „Verbindung
gestartet“. Die Serveridentität prüft Windows selbst: Hat der Zielrechner ein
Zertifikat der eigenen RDP-Zertifizierungsstelle und wird über den Namen im
Zertifikat verbunden, kommt keine Warnung; sonst zeigt Windows seine eigene.
Die Ausnahme „Serveridentität“ gibt es weiterhin, aber nur noch bewusst unter
**Bearbeiten**. Dass bei einer IP-Adresse das Webkonto entfällt, zeigt die
Detailansicht. Gewarnt wird weiterhin, wenn die Maschine belegt oder für
jemand anderen gebucht ist und wenn Windows für das Ziel Anmeldedaten eines
anderen Kontos gespeichert hat.

**Anmelden als gilt.** Verbunden wird mit genau dem Konto, das im Dropdown
steht. Bisher ersetzte das Portal es bei einer fremden Sitzung still durch das
Konto dieser Sitzung. Wer eine laufende Sitzung übernehmen will, wählt sie als
**Angemeldet · …**. Hat Windows für das Ziel Anmeldedaten eines *anderen*
Kontos gespeichert (`TERMSRV/<ziel>`), würde Remotedesktop diese nehmen; das
Portal fragt dann vor dem Start, ob der gespeicherte Eintrag entfernt werden
soll. Gelesen wird dabei nur der Kontoname, nie das Kennwort.

**Kein Text wird mehr abgeschnitten, auch nicht bei größerer Windows-Schrift.**
Karten werden so hoch wie ihr Inhalt, lange Namen enden mit „…“ und stehen voll
im Tooltip, die Filterleiste und die Knopfzeilen in Admin und Maschinendetails
brechen bei Platzmangel um, und Adminbereich und Maschinendetails scrollen
unterhalb der Kopfzeile. Rückfragen werden so breit wie ihre Knöpfe; die
Standardknöpfe heißen jetzt „Abbrechen“ statt „Cancel“. Geprüft wird das bei
9 und 12 pt in einem 1280 × 720-Fenster (`tests/test_text_fit.py`).

**Entra-Konten in der richtigen Schreibweise.** Ohne Entra-Webanmeldung – und
bei einer IP-Adresse gibt es keine – braucht Remotedesktop ein Entra-Konto als
`AzureAD\becker@prof-kirschke.de`. Das Portal schreibt eine bloße E-Mail-Adresse
jetzt selbst so, sobald die Maschine Entra-Sitzungen meldet oder du selbst mit
einem Entra-Konto angemeldet bist. Vorher lehnte Windows mit „nicht zur
Remoteanmeldung autorisiert“ ab, obwohl normales RDP ging.

**Aufschaltmeldungen gehören zum Rechner, von dem verbunden wurde.** Eine Meldung
trägt den Namen des Portal-PCs und gilt nur für eine Sitzung, die Windows als von
dort aufgebaut meldet. Übernimmt ein anderer Rechner die Sitzung, gilt sie nicht
mehr. Vorher konnte sich die Meldung einer abgebrochenen Verbindung an die
Sitzung eines Kollegen unter demselben Konto hängen. **Agent 1.7.2 verteilen.**

**0.9.5 behebt den Startabbruch von 0.9.4** („No module named 'win32timezone'“).
Ein Fehler beim Aufräumen alter Anmeldedaten verhindert den Start nicht mehr.

**RDP scheitert nicht mehr am Freigabekonto.** Wer im Freigabedialog die
Zugangsdaten speichern ließ, bekam einen Windows-Eintrag für den ganzen Server.
Den nahm auch Remotedesktop: Es meldete sich als `PortalLeser` an, egal welches
Konto gewählt war, und Windows lehnte mit „nicht zur Remoteanmeldung autorisiert“
ab. Ab 0.9.4 merkt sich das Portal das Freigabekonto unter einem eigenen Eintrag
(`KirschkeRDPPortal:Freigabe:<Server>`), den Remotedesktop nicht nutzt, und
verbindet Inventar-, Protokoll- und Statusfreigaben beim Start selbst. Alte
Einträge, die das Portal selbst für `PortalLeser` angelegt hatte, entfernt es beim
Start. Findet es vor dem Verbinden trotzdem noch einen Server-Eintrag, sagt es das
und bietet an, ihn zu entfernen.

**Eigene Konten bei jeder Maschine.** Die Konten unter *Einstellungen → Weitere
eigene Windows-Konten* stehen jetzt bei jeder Maschine unter „Anmelden als“.
Entra-Profilnamen wie `AzureAD\ChristianBecker` bleiben draußen – mit ihnen ist
keine Anmeldung möglich; dafür `AzureAD\name@firma.de` eintragen.

**Gemeinsam genutzte Konten.** Ein Häkchen in derselben Liste markiert ein Konto,
unter dem sich mehrere Menschen anmelden, etwa `.\RDPUser` auf den
Rechenmaschinen. Dessen Sitzung gilt nur dann als eigene, wenn Windows diesen PC
als RDP-Client meldet. Vorher zeigte jedes Portal die RDPUser-Sitzung eines
Kollegen als eigene an. Eine getrennte Sitzung eines gemeinsamen Kontos hat
keinen Client mehr und gilt deshalb als fremd belegt.

**Agent-Setup auf Rechnern mit langem Namen.** Das Setup meldete auf einem
Rechner wie `Remote-Ettlingen` „keinen aktuellen Online-Status“, obwohl der
Agent lief. Windows kürzt `%COMPUTERNAME%` auf 15 Zeichen, der Agent meldet den
vollen Namen. Dabei blieb auch die Freigabe `RDP-Protokoll` aus. Agent-Setup
1.7.3 erkennt beide Schreibweisen, nennt bei einem Fehlschlag den Grund und zeigt
Freigabepfade mit dem vollen Rechnernamen an. Betroffene Rechner einfach noch
einmal einrichten.

**Die Karte nennt Person und Konto:** „Belegt von Christian Becker als
NB12KI\Codex“. Vorher stand dort nur die Person, die über das Portal verbunden
hat, und nicht, unter welchem Windows-Konto die Sitzung läuft.

**Wer eine Maschine belegt, steht wieder richtig auf der Karte.** Aufschaltmeldungen
werden der Sitzung in jeder Schreibweise des Kontos zugeordnet
(`Rechenknecht` = `WORKSTATION\Rechenknecht`), bei mehreren gilt die jüngste,
und die Nachmeldung unter der vom Agenten gemeldeten Schreibweise läuft bei jeder
neuen Verbindung. Vorher nannte die Karte oft das Konto statt der Person, hielt
Portal-Verbindungen für „direkt verbunden“ oder nannte nach einer Übernahme noch
den Vorgänger. **Der Agent muss dafür mit verteilt werden**; ein älterer Agent
verwirft eine anders geschriebene Meldung nach 30 Minuten.

## Verbindungsassistent

Beim ersten Start ohne Maschinen öffnet sich der **Verbindungsassistent**
automatisch; später jederzeit über **Einstellungen → Agenten, Zuordnung und
Datei-Fallback → Verbindungsassistent öffnen** oder **Admin → + Maschine**.

Drei Wege:

1. **Agenten im Netzwerk suchen** (Standard). Der Assistent klopft jede Adresse
   des gewählten Bereichs daraufhin ab, ob dort der Statuskanal des Agenten
   antwortet. Vorgeschlagen werden das eigene /24 sowie `192.168.2.0/24` und
   `192.168.20.0/24`. Die Suche ändert auf den Zielrechnern nichts und läuft
   nur auf Knopfdruck, nie im Hintergrund. Mehr als 1024 Adressen werden
   abgelehnt, statt eine unvollständige Suche vorzutäuschen.
2. **Diesen lokalen Rechner** – wie bisher über die Windows-Netzwerkkonfiguration.
3. **Zielrechner manuell** – wie bisher über DNS-Vorwärts- und Reverse-Lookup.

Gefundene Agenten erscheinen mit Maschinen-ID, Hostname und Agent-Version. Auf
der Zuordnungsseite wird je Agent entschieden, ob eine **neue Maschine angelegt**
oder eine **vorhandene verknüpft** wird. Der **Standort** ergibt sich aus der
IP-Adresse (`192.168.2.x` = Ettlingen, `192.168.20.x` = München) und bleibt
änderbar. Für jede eingerichtete Maschine setzt das Portal anschließend den
Datei-Fallback `\\RECHNER\RDP-Status` und verbindet ihn.

**Beim Start verbindet das Portal alle eingerichteten Statusfreigaben selbst.**
Vorher überlebten Pfad und gespeicherte Zugangsdaten zwar den Neustart, die
SMB-Sitzung aber nicht - der Datei-Fallback und mit ihm der Live-Kanal (dessen
Pipe-Ziel vom selben Server stammt) blieben tot, bis jemand den
Einrichtungsdialog erneut durchlief.

**Netzwerkzugriffe halten das Fenster nicht mehr an.** Eine Live-Antwort
liest die Fallbackordner nicht mehr neu ein, sondern verwendet den letzten
Ordner-Scan, den der Statustakt im Hintergrund erneuert. Die Antworten eines
Statuslaufs werden zu einer Aktualisierung gebündelt. Aufschaltmeldungen gehen
in einem eigenen Thread an den Agenten; eine nicht zugestellte Meldung wird
frühestens nach 5 s erneut versucht. Ob ein vom Portal gestartetes RDP-Fenster
noch offen ist, wird höchstens einmal pro Sekunde abgefragt – ein gerade
geschlossenes Fenster kann also bis zu einer Sekunde nachwirken.

Rechnernamen werden beim Start alle gleichzeitig nachgeschlagen. Ein Name ohne
schnelle DNS-Antwort (150 ms) gilt vorerst als nicht auflösbar, und das Portal
nimmt den nächsten Bezeichner, meist die IP; die Antwort wird im Hintergrund
nachgereicht. Eine abgelaufene Antwort bleibt gültig, bis die neue da ist.
Vorher kostete jeder nicht auflösbare Name den Start bis zu 2 s und im Betrieb
alle 30 s erneut.

**Hänger im Log:** Reagiert die Oberfläche länger als 200 ms nicht, steht im
`portal.log` eine WARNING mit der Codestelle, an der sie hängt, und danach die
Gesamtdauer. Die Zeile „UI-Wachhund aktiv“ bestätigt beim Start, dass die
Überwachung läuft. Bei der Store-Version von Python liegt das Log unter
`%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_…\LocalCache\Local\KirschkeRDPPortal\logs`.

### Lesekonto

Das Portal liest Statusfreigaben und den Agent-Statuskanal als `PortalLeser`,
dem schreibgeschützten lokalen Konto, das das Agent-Setup auf jedem Ziel-PC
anlegt. Es gibt zwei Quellen, höchste zuerst:

1. **Auf diesem PC hinterlegt** – wer im Assistenten oder in den Einstellungen
   ein Konto einträgt, überstimmt damit die Auslieferung. Windows speichert es
   in der Anmeldeinformationsverwaltung dieses Benutzers; in keiner Portaldatei.
2. **Mit der Portalversion mitgeliefert** – siehe
   `portal_app/services/reader_account.py`. Im Quellcode steht dort **kein**
   Kennwort; es wird beim Bauen einer Auslieferung eingetragen, so wie der
   Admin-Hash in `admin_security.py` gepflegt wird.

Ist beides vorhanden, wird zuerst das mitgelieferte und danach das hinterlegte
Kennwort probiert. Ist keines vorhanden, fragt der Assistent sofort. Ein Agent,
der zwar läuft, den das Portal aber nicht lesen darf, wird als solcher
ausgewiesen - das ist eine Rechtefrage, keine Erreichbarkeitsfrage.

**Zentrale Verwaltung:** Unter **Einstellungen** zeigt eine Tabelle je Maschine
die Agent-Zuordnung, die Quelle des letzten Status (Live-Kanal, Datei-Fallback
oder keine Meldung) und den Fallbackordner. Die Zuordnung ist dort direkt
umstellbar; **Alle Fallbacks jetzt verbinden** baut die SMB-Sitzungen neu auf.

### Gemeinsame Daten nur über das Netzwerk

Seit 0.9.0 gibt es keine SharePoint- oder OneDrive-Anbindung mehr. Gemeinsame
Daten laufen ausschließlich über das Netzwerk: die Pipe und die Freigabe
`\\PC\RDP-Status` jedes Agenten, optional ein Protokollordner und optional ein
**gemeinsames Inventar** auf einer SMB-Freigabe.

**Ohne gemeinsames Inventar** führt jedes Portal seine Maschinen für sich in
`state\portal-state.json` neben der EXE (nach dem Setup im eigenen Profil).
Reservierungen und Aufschaltungen laufen trotzdem über die Agenten und bleiben
gemeinsam. Beim Update den `state`-Ordner beibehalten.

**Gemeinsames Inventar:** Unter **Admin → Gemeinsames Inventar einrichten** eine
Freigabe mit Schreibrecht eintragen, z. B. `\\SERVER\RDP-Portal`. Das Portal
prüft vorher durch einen echten Schreibversuch. Liegt dort noch nichts, wird der
eigene Stand hinkopiert; liegt dort schon ein Inventar, gilt dieses, und der
eigene Stand bleibt unverändert liegen. Danach liegen Maschinen,
Reservierungen, die Kontoliste und – ohne eigenen Protokollordner – das
Ereignisprotokoll auf der Freigabe. Jedes Portal trägt die Freigabe für sich ein.

- **Keine Konflikte:** Jeder Schreibvorgang hält eine Byte-Sperre auf der
  Freigabe, liest den aktuellen Stand, führt ihn per Drei-Wege-Abgleich mit den
  eigenen Änderungen zusammen und ersetzt die Datei atomar. Änderungen an
  verschiedenen Maschinen kommen beide an; haben zwei Portale *dieselbe*
  Maschine geändert, wird der zweite Schreibvorgang mit „Paralleländerung
  erkannt“ abgelehnt statt still überschrieben. Liest gerade ein anderer PC die
  Datei, wartet das Ersetzen bis zu 2 s.
- **Änderungen anderer Portale** werden alle 5 s im Hintergrund erkannt und
  nachgeladen; ein hängender Server hält das Fenster dabei nicht an.
- **Freigabe nicht erreichbar:** Das Portal legt dort nichts an und schreibt
  nichts hin. Es startet im **Notbetrieb** mit der lokal gemerkten Kopie des
  zuletzt gelesenen Stands und sagt das beim Start und im Adminbereich.
  Änderungen im Notbetrieb werden nicht geteilt und beim nächsten Start mit
  erreichbarer Freigabe nicht übernommen.
- **Wieder lokal führen** übernimmt den aktuellen gemeinsamen Stand als eigenen;
  der vorherige eigene Stand bleibt als `portal-state.vorher.json` liegen, die
  Freigabe wird nicht verändert.

**Kein Ordner in OneDrive oder SharePoint:** Inventar, Protokollordner und
Fallbackordner werden abgelehnt, wenn sie in einem synchronisierten Ordner
liegen. Erkannt wird das über die OneDrive-Umgebungsvariablen, die OneDrive-Konten
und eingebundenen SharePoint-Bibliotheken in der Registry, die Sync-Roots von
Windows, die Cloud-Dateiattribute, OneDrive-Ordnernamen und WebDAV-Pfade. Wird
die portable EXE aus einem solchen Ordner gestartet, legt sie ihren Stand unter
`%LOCALAPPDATA%\KirschkeRDPPortal\daten` ab. Ein älterer Eintrag, der in
OneDrive zeigt, wird ignoriert und beim Start gemeldet.

**Migration von 0.8.x:** Der alte Standardordner in der SharePoint-Bibliothek
und der Eintrag `storage_directory` in `storage-config.json` werden nicht mehr
gelesen; ein Stand in `state\` neben der EXE gilt unverändert weiter. Wer
gemeinsam arbeiten will, richtet einmal das gemeinsame Inventar ein – auf dem
ersten PC wird dabei dessen Stand auf die Freigabe kopiert, alle weiteren
übernehmen ihn. Der Agent 1.7.0 muss mitverteilt werden (Graph-Zweig entfernt).
Persönliche Kontowahl und Benutzereinstellungen bleiben im jeweiligen Windows-Profil.

Unter **Maschinen → Details → Datei-Fallback einrichten …** erhält jede
Maschine ihre eigene SMB-Freigabe. Das Portal speichert auf Wunsch nur die
Zugangsdaten in der Windows-Anmeldeinformationsverwaltung des aktuellen Benutzers;
Kennwörter gelangen nicht in Portaldateien.

Agent 1.3.0 startet rechnerweit als SYSTEM über die Windows-Aufgabenplanung und
erfasst RDP- und Konsolensitzungen mit Anmeldezeiten und einem begrenzten Verlauf.
Der Agent schreibt als SYSTEM in seinen lokalen Ordner
`C:\RDP-Portal-Daten\agenten-status`. Das Portal liest dessen Freigabe
`\\ZIELRECHNER\RDP-Status` nur als Datei-Fallback; der direkte Statuskanal bleibt
der bevorzugte Weg.
Das Testpaket enthält jetzt `Kirschke-RDP-Portal-Setup.exe` und
`Kirschke-RDP-Agent-Setup.exe`, jeweils mit Deinstallation über Windows.

**Schnellstart:** [Kurzanleitung für Client, Anmeldekonten und Agent-Setup](docs/testbetrieb-kurz.md).
Den Fallback je Maschine in deren Details einstellen. Beim Update bleibt der frühere
globale Ordner als Alt-Standard wirksam, bis die jeweilige Maschine einen eigenen
Pfad erhalten hat.
Pro Maschinenkarte gibt es jetzt **Anmelden als** mit **+ Benutzer hinzufügen …**.
**Agent-Diagnose** im Dashboard zeigt den gelesenen Ordner, Dateien und Zuordnungen.
Bei abweichender Agent-ID unter **Maschine → Details → Agent zuordnen …** den
passenden Agenten auswählen. Die Zuordnung bleibt im Inventar gespeichert.
**Diagnose kopieren** kopiert den vollständigen Prüfbericht zur Fehlersuche.
Die Agent-Setup-EXE enthält alle benötigten Agent-Dateien und installiert ohne ein
intern gestartetes PowerShell-Skript; auf dem Ziel-PC ist weder Python noch eine
gelockerte PowerShell-Ausführungsrichtlinie nötig. Bei der ersten Installation
richtet sie außerdem `PortalLeser` und `RDP-Status` mit einem selbst vergebenen
Kennwort ein; das Konto erhält ausschließlich Leserechte auf den Statusordner.
Nach dem Agent-Build: `dist-agent/Kirschke-RDP-Agent-Setup.exe`.
Nach beiden Builds erstellt `python deployment/package_pilot.py` das vollständige
Testpaket `dist/Kirschke-RDP-Testbetrieb.zip` einschließlich Kurzanleitung.

Für den ersten Testbetrieb sind der [Prüfbericht und die Abnahmeliste](docs/code-review-testbetrieb.md)
maßgeblich. Der aktive Programmstart verwendet lokale JSON-Dateien und optionale Agent-Statusdateien.
Die vorhandenen Entra-/Windows-Dienst-Module sind noch keine integrierte Betriebsvariante.
Remote-Adminbefehle und die bisherigen Dienstinstallationsschalter sind im Pilot deaktiviert.

Das Maschinendashboard fragt den geschützten Agent-Statuskanal automatisch ab
(Standard: 5 Sekunden, einstellbar von 2 bis 60 Sekunden) und zeigt Quelle und Alter
jedes Zustands. Die Agent-JSON bleibt Fallback. Eigene Sitzungen können nach erneuter
Windows-Identitätsprüfung vom SYSTEM-Agenten abgemeldet werden. Dazu müssen auch
Sitzungsnummer, Anmeldezeit und der vom Agenten gemeldete RDP-Client passen. Die
administrative Notfall-Abmeldung verlangt echte Windows-Administrator-Anmeldedaten
des Zielrechners; das Kennwort wird nicht gespeichert. `PortalLeser` allein erhält
keine administrative Abmeldeberechtigung.

Neue Installationen starten ohne Beispielmaschinen. Bestehende Inventare bleiben erhalten.
Der Portal-Adminzugang verwendet ab Version 0.6.3 auf allen PCs dasselbe globale,
mit dem Rollout festgelegte Passwort. Im Programm liegt nur ein gesalzener
PBKDF2-HMAC-SHA256-Hash. Es gibt keine lokale Ersteinrichtung oder Passwortänderung;
bisherige `admin-security.json`-Dateien werden nicht mehr ausgewertet.
Passwortänderungen werden über eine neue Portalversion verteilt. Nach fünf
Fehlversuchen ist die Anmeldung in der laufenden Portalinstanz 15 Minuten gesperrt.
Die Freischaltung gilt jeweils bis zum Sperren oder Schließen dieser Portalinstanz.
Windows prüft weiterhin Freigabezugriffe und administrative Abmeldungen am Zielrechner.
Im optionalen AD-Modus bleibt die Windows-Gruppenprüfung aktiv; der Passwort-Fallback
ist dort standardmäßig ausgeschaltet.
Programmlogs liegen unter `%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log` und werden rotiert.

Vorprüfung ohne RDP-Anmeldung oder Datenänderung:

```powershell
python -m portal_app.preflight --storage "C:\Pilot\RDP-Portal" --json
```

Für gemeinsame Daten ausschließlich SMB-Freigaben verwenden; OneDrive- und
SharePoint-Ordner lehnt das Portal ab (siehe oben).

A Windows application for managing office workstations with RDP connections, session tracking, and admin functions.

## Project Structure

```
kirschke-rdp-portal/
├── portal_app/           # Main portal application
│   ├── app.py            # Application entry point
│   ├── models/          # Data models
│   ├── ui/              # User interface components
│   │   ├── widgets/     # Reusable UI widgets
│   │   └── design/      # Kirschke Corporate Design system
│   ├── auth/            # Authentication (Phase 2)
│   ├── services/       # Business services (Phase 2)
│   └── rdp/             # RDP functionality
│       ├── generator.py # RDP file generator
│       └── launcher.py   # RDP session launcher
├── workstation_agent/    # Workstation agent (Phase 3)
│   └── service.py       # Windows service
├── shared/              # Shared modules
│   ├── enums/           # Enumerations
│   ├── schemas/         # Pydantic schemas
│   └── validation/      # Validation utilities
├── tests/               # Tests
├── deployment/          # Deployment configuration
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## Features Implemented (Phase 1)

- [x] PySide6 application with Kirschke Corporate Design
- [x] Workstation overview with table view
- [x] Filtering by site, status, agent status, and search
- [x] Workstation detail view with all information
- [x] Session log view with filtering
- [x] Manual flag system (Berechnung laeuft, Wartung, Gesperrt)
- [x] Blocking logic for connections and logoff
- [x] Validated RDP file generation
- [x] Secure mstsc.exe launching
- [x] Local mstsc.exe process monitoring with duplicate-start protection
- [x] Occupied-session warnings and connection blocking, including disconnected sessions
- [x] Close warning while portal-launched RDP windows are still running
- [x] Mock data for development
- [x] User roles (User vs Admin)
- [x] Local JSON persistence for the test build
- [x] Editable workstation and general RDP profiles
- [x] Workstation and free-target ping tools
- [x] Two-week workstation reservation calendar
- [x] Password-protected local admin session
- [x] CSV/JSON session-log export
- [x] Correct local WTS session enumeration and RDP/console separation
- [x] Credential-free local agent status bridge for end-to-end testing
- [x] Agent staleness/offline evaluation in the portal
- [x] Asynchronous local `ipconfig /all` display with copy action

## Features Planned

### Phase 2: Entra Integration
- [ ] Microsoft Entra ID authentication (MSAL)
- [x] Gemeinsames Inventar auf einer SMB-Freigabe mit Sperre und Drei-Wege-Abgleich
- [ ] Launch event auditing

SharePoint-Listen und Microsoft Graph sind seit 0.9.0 verworfen und entfernt.

### Phase 3: Windows Agent
- [ ] Windows service
- [x] WTS-API integration for session tracking
- [x] Event detection (Logon, Reconnect, Disconnect, Logoff)

### Phase 4: Admin Actions
- [ ] Admin command processing
- [ ] Session disconnect with confirmation
- [ ] Session logoff with warning and override
- [ ] Admin-override with mandatory reason
- [ ] Command execution confirmation
- [ ] Audit logging
- [ ] CSV/JSON export

### Final
- [x] PyInstaller packaging (portable Windows folder build)
- [ ] Intune deployment documentation
- [ ] Comprehensive tests
- [ ] User documentation

## Requirements

- Python 3.12+
- Windows operating system
- PySide6
- MSAL Python (Phase 2)
- Pydantic
- Requests

## Installation

```bash
# Clone or navigate to the repository
cd kirschke-rdp-portal

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .[dev]

# Run the application
python -m portal_app.app

# Or use the entry point
rdp-portal
```

### Windows (PowerShell)

Run the following commands from the `kirschke-rdp-portal` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m portal_app.app
```

The recommended start is `python -m portal_app.app`. Direct starts via `python portal_app/app.py` are also supported.

## Portable Windows-Testversion

Erstellt eine portable Ordner-Version ohne Konsolenfenster. PyInstaller ist mit den Entwicklungsabhängigkeiten
installiert; der Build benötigt keinen Administratorzugriff.

```powershell
.\deployment\build_portable.cmd
```

Danach die komplette Ausgabe aus `dist\Kirschke-RDP-Portal\` weitergeben und
`Kirschke-RDP-Portal.exe` starten. Der Ordner darf nicht aufgeteilt werden, weil er die Qt-Laufzeitdateien enthält.
Für eine einzelne EXE kann optional `.\deployment\build_portable.cmd -OneFile` verwendet werden; sie startet
langsamer und ist für den ersten Test nicht empfohlen.

## Optionaler Standalone-Agent für Sitzungsstatus

Der Agent ist eine zweite, portable Windows-Anwendung ohne Python-Abhängigkeit. Er meldet den echten
RDP-Sitzungszustand eines Ziel-PCs über seine Statusfreigabe und die Pipe. Build, Installation und die Grenzen des
benutzerbasierten Pilotbetriebs sind in [docs/agent-installation.md](docs/agent-installation.md) beschrieben.

```powershell
.\deployment\build_agent.cmd
```

**Empfohlener Weg:** `dist-agent\Kirschke-RDP-Agent-Setup.exe` als Administrator starten. Dieses Setup ist
der unterstützte Installationsweg; es installiert rechnerweit als SYSTEM über die Aufgabenplanung, richtet
auf Wunsch `PortalLeser` und die Freigabe `RDP-Status` ein und benötigt auf dem Ziel-PC weder Python noch
eine gelockerte PowerShell-Ausführungsrichtlinie.

Daneben liegt im Ordner noch `Install-Agent.cmd`, das den älteren PowerShell-Installer
(`deployment/install_agent.ps1`) startet. Er richtet den Autostart nur für den angemeldeten Benutzer ein und
legt **kein** Lesekonto und **keine** Freigabe an. Beide Wege registrieren dieselbe geplante Aufgabe, also
nur einen davon verwenden. Der PowerShell-Weg bleibt ausschließlich als Rückfallebene erhalten.

## Active Directory (optional)

Die Admin-Verwaltung kann gespeicherte RDP-Zugriffe nach Bestätigung mit AD-Gruppen
`RDP-<Maschinen-ID>` abgleichen. Die Vorbereitung auf einem Verwaltungsrechner ist in
[docs/active-directory-setup.md](docs/active-directory-setup.md) beschrieben.
Für die vollständige Pilotabnahme siehe auch
[docs/pilotbetrieb-anleitung.md](docs/pilotbetrieb-anleitung.md).
Für ein Büro ohne Active Directory gibt es die
[No-AD-Pilotanleitung](docs/no-ad-pilotbetrieb.md).

## Repository Hygiene

The repository contains source code, configuration examples, tests, and documentation only. Local environments,
Python/test caches, build output, and runtime logs are excluded through the root `.gitignore`. Recreate a local
environment with the installation commands above instead of committing it.

When a change affects setup, usage, configuration, or user-visible behavior, update this README concisely in the
same change.

## Running with Different User Roles

Der aktive Start erkennt das angemeldete Windows-Konto. Den Adminbereich über die
Oberfläche freischalten. Änderungen an `get_current_user()` in `app.py` konfigurieren
den tatsächlich verwendeten `MainWindow`-Benutzer nicht.

## Configuration

### Environment Variables (Phase 2+)

Die Anwendung liest Umgebungsvariablen; `.env`-Dateien werden nicht automatisch geladen.
Die folgenden Cloud-Einstellungen gelten nur für die noch nicht integrierten Cloud-Module:

```ini
# Entra ID
TENANT_ID=your-tenant-id
PORTAL_CLIENT_ID=your-client-id
AUTHORITY=https://login.microsoftonline.com/your-tenant-id

# Agent
AGENT_POLL_INTERVAL=30
```

See `.env.example` for all available options.

## Corporate Design

The application uses the Kirschke Corporate Design system as specified in the project requirements:

- **Brand Colors:** #668BB0 (Blue), #231F20 (Charcoal), #778C77 (Green), #80A3CA (Light Blue)
- **Neutral Colors:** #F4F5F2 (Background), #F7F7F3 (Paper), #FFFFFF (Surface)
- **Typography:** Segoe UI (fallback to Inter, Arial, Helvetica)
- **Spacing:** Consistent spacing system (2px, 4px, 8px, 16px, 24px, 32px, etc.)

## Security Notes

- The shared portal admin password ships only as a PBKDF2-HMAC-SHA256 hash
  (310 000 iterations, random 16-byte salt). Its verifier is identical across
  installations; profile-local credentials cannot override it. Five failed
  attempts pause the running portal's password gate for 15 minutes.
- RDP profiles are validated to prevent injection attacks: control characters are
  rejected at the output boundary, and the target host is validated against an
  allowlist pattern.
- Every child process is started from an absolute `System32` path, never a bare
  executable name, so `CreateProcess` cannot pick up a planted binary from the
  working directory. A test enforces this repository-wide
  (`tests/test_windows_tools.py`).
- mstsc.exe is launched with explicit argument lists (no shell=True).
- Generated `.rdp` files carry the target and user name. They are deleted when the
  portal closes and leftovers from a crashed run are removed at the next start.
- The Active Directory sync passes its payload base64-encoded into PowerShell
  instead of interpolating values into the script text.
- The agent's live status channel is restricted by SDDL to SYSTEM, local
  administrators and the read-only `PortalLeser` account; `PortalLeser` is denied
  interactive, remote-interactive, batch and service logon.
- Share credentials are kept as generic Credential Manager entries named
  `KirschkeRDPPortal:Freigabe:<server>`, never as a server-wide domain credential.
  Windows applies a domain credential to every logon at that server, including
  Remote Desktop; the portal removes such entries it created for `PortalLeser`
  in earlier versions and warns before connecting if one remains.
- Agent snapshots read from an SMB share are untrusted input and are bounded in
  file size, file count, list length and field length.
- Signing out a session requires a fresh agent reply with matching session ID,
  user and logon time, a request no older than 30 seconds, an unused request ID,
  and either proven session ownership or real administrator credentials for the
  target computer. Note the UAC caveat in
  [docs/no-ad-pilotbetrieb.md](docs/no-ad-pilotbetrieb.md) for local accounts.
- Der Agent-Suchlauf fragt nur, ob die Named Pipe des Agenten existiert, und
  holt mit dem Lesekonto denselben schreibgeschützten `STATUS/1`-Schnappschuss,
  den das Dashboard ohnehin verwendet. Er schreibt auf keinem Ziel etwas, läuft
  nur auf ausdrücklichen Start und lehnt Bereiche über 1024 Adressen ab.
- Ein mit der Auslieferung mitgeliefertes Lesekonto-Kennwort liegt im Programm im
  **Klartext**, weil eine SMB-Anmeldung keinen Hash verwenden kann. Wer an die
  EXE kommt, erhält damit Lesezugriff auf den Statusordner jedes Arbeitsplatzes.
  `PortalLeser` ist dafür bewusst eng geschnitten: nur Lesen auf einen Ordner,
  kein Administrator, keine Abmeldeberechtigung, und interaktive, Remote-,
  Batch- und Dienstanmeldung sind ihm verwehrt. Wer das nicht will, lässt
  `BUNDLED_READER_PASSWORD` leer; dann fragt der Assistent einmal pro PC.
- Ein auf einem PC hinterlegtes Lesekonto überstimmt das mitgelieferte, damit
  eine neue Portalversion eine Korrektur vor Ort nicht stillschweigend aufhebt.
- Beim Wiederverbinden einer Statusfreigabe wird nie eine SMB-Verbindung getrennt,
  die eine andere Anwendung hält; eine bestehende Sitzung unter einem anderen
  Konto wird gemeldet, nicht ersetzt.
- Admin actions require explicit confirmation and reasoning.
- The Graph/SharePoint code is removed (0.9.0 / Agent 1.7.0); no data leaves
  the local network. The remaining Entra login code is **not integrated and
  untested**; see [docs/phase2-status.md](docs/phase2-status.md).
- Kein Ordner, den das Portal beschreibt, darf in OneDrive oder SharePoint
  liegen; das gemeinsame Inventar muss auf einer Netzwerkfreigabe liegen. Wer
  darauf Schreibrecht hat, kann das Inventar aller Portale ändern – die
  Freigabe deshalb nur für die Portalnutzer beschreibbar machen.

## Testing

```bash
# Run all tests
pytest

# Run pilot regression tests
pytest tests/test_pilot_regressions.py

# With coverage (requires the dev extra)
pytest --cov=portal_app --cov=workstation_agent --cov=shared
```

Lint and type checks use the configuration in `pyproject.toml`:

```bash
ruff check portal_app workstation_agent shared deployment tests
mypy portal_app workstation_agent shared deployment
```

Current state (11.09.2026): **327 tests green, `ruff check` clean, 67 % line
coverage** of the code that runs in the pilot. `mypy` reports 123 remaining
findings, mostly missing annotations (`no-untyped-def`) and possible `None`
dereferences (`union-attr`) — a known backlog, not a clean baseline.

`ruff check` must stay clean. Do not add a blanket `noqa`; either fix the finding
or record the reason in the `per-file-ignores` section of `pyproject.toml`. The
coverage figure excludes the unintegrated Phase 2 modules listed in
[docs/phase2-status.md](docs/phase2-status.md), which have no tests at all.

### Test the Windows agent locally

```powershell
# One-time live WTS diagnosis
python -m workstation_agent.service --status

# Publish a continuously refreshed status for a test machine
$env:WORKSTATION_ID="WS-001"
python -m workstation_agent.service --run
```

Der Agent schreibt auf jedem Ziel-PC in seinen lokalen `status_directory`, empfohlen
`C:\RDP-Portal-Daten\agenten-status`. Im Portal wird auf der jeweiligen Maschinenseite
der dazu freigegebene UNC-Pfad, etwa `\\NB12KI\RDP-Status`, eingestellt.

The portal reads this local test status automatically every five seconds. A snapshot is matched by
workstation ID or hostname. After 90 seconds without an update it is shown as stale and after five
minutes as offline. Each machine has its own client-local fallback folder. The portal
no longer inherits `AGENT_STATUS_DIR` from Windows.

## Known Limitations (Phase 1)

1. **No actual authentication** - Uses mock users for development
2. **Kein Cloudbetrieb** - SharePoint und Graph sind entfernt; gemeinsame Daten laufen nur über Netzwerkfreigaben und die Agenten.
3. **Agent transport** - Statusdateien werden über SMB gelesen. Vollständige Agent-Ereignisse werden noch nicht in das lokale Portal-Log übertragen.
4. **Local process monitoring only** - The portal detects the lifetime of RDP clients it started; closing mstsc.exe does not prove that the remote Windows session logged off
5. **Remote admin commands disabled** - Das Portal kann eigene lokale RDP-Fenster schließen; ein entferntes Windows-Logoff über die Befehlswarteschlange ist im Pilot nicht freigegeben. Die Abmeldung über den geschützten Statuskanal ist freigegeben und geprüft.
6. **Administrative Abmeldung bei lokalen Konten** - Die UAC-Remoteeinschränkung lässt die Prüfung für lokale Administratorkonten fehlschlagen, solange `LocalAccountTokenFilterPolicy` nicht gesetzt ist. Fehlerrichtung ist sicher (Ablehnung). Siehe [docs/no-ad-pilotbetrieb.md](docs/no-ad-pilotbetrieb.md).
7. **Nur ein Live-Client gleichzeitig** - Der Statuskanal des Agenten bedient eine Verbindung nach der anderen. Jeder Schritt ist zeitlich begrenzt, sodass kein Client den Kanal blockieren kann; mehrere Portale auf demselben Agenten serialisieren sich aber.
8. **Zwei Installationswege für den Agenten** - Unterstützt ist `Kirschke-RDP-Agent-Setup.exe`. `Install-Agent.cmd` startet den älteren PowerShell-Installer ohne Lesekonto und Freigabe; beide registrieren dieselbe geplante Aufgabe.

These will be addressed in subsequent phases.

## License

Proprietary - Kirschke

## Contact

For questions or issues, contact: it@prof-kirschke.de
