# Kirschke RDP Workstation Portal

## Serverloser Projektplan und Copy-and-paste-Prompt für Codex oder Claude

Version: 2.0  
Stand: 27.08.2026

---

## 1. Verbindlicher Projektumfang

Entwickle eine lokale Windows-Anwendung zur Verwaltung der Kirschke-Büro-Workstations.

Der Umfang ist bewusst schlank:

- Workstations mit hinterlegten RDP-Verbindungsdaten anzeigen;
- eine RDP-Verbindung per Klick mit mstsc.exe starten;
- tatsächliche RDP-Anmeldung, Wiederverbindung, Trennung und Abmeldung protokollieren;
- anzeigen, welcher Benutzer wann auf welcher Workstation angemeldet war;
- einen Status wie „Berechnung läuft“, „Wartung“ oder „Gesperrt“ manuell setzen und aufheben;
- bei aktivem Sperrstatus normale Verbindungen und Logoff-Aktionen in der Anwendung blockieren;
- Admin-Override nur mit Bestätigung und Begründung zulassen;
- Administratoren das Trennen oder Abmelden einer Sitzung ermöglichen;
- Workstation-Daten, Flags, Befehle und Logs zentral in SharePoint-Listen speichern;
- Microsoft Entra ID für Benutzeridentität und Rollen verwenden.

Nicht Bestandteil des MVP:

- keine automatische Erkennung laufender Berechnungen;
- keine Analyse von CPU-, GPU- oder Prozessauslastung;
- keine Berechnungswarteschlange;
- kein eigener dauerhaft laufender Portalserver;
- keine Browserübertragung der RDP-Sitzung;
- keine Speicherung von Windows-Passwörtern in SharePoint oder der Anwendung.

Das manuelle Flag ist die fachliche Wahrheit. Die Anwendung versucht nicht, dessen Richtigkeit automatisch zu erraten.

---

## 2. Architektur ohne eigenen Server

Das System besteht aus:

1. **Lokaler Portal-App** auf den Benutzer- und Admin-PCs.
2. **Windows-Agent als Dienst** auf jeder verwalteten Workstation.
3. **SharePoint-Listen** als zentrale Daten- und Koordinationsschicht.
4. **Microsoft Graph** für Lese- und Schreibzugriffe.
5. **Microsoft Entra ID** für Anmeldung und Rollen.
6. **mstsc.exe** für die eigentliche RDP-Verbindung.

Es wird kein eigener FastAPI-, Datenbank- oder Webserver benötigt. SharePoint Online übernimmt die zentrale Verfügbarkeit. Die lokale Anwendung startet mstsc.exe direkt.

~~~text
Lokale Portal-App  <->  Microsoft Graph  <->  SharePoint-Listen
        |
        +-> erzeugt lokale .rdp-Datei
        +-> startet mstsc.exe

Windows-Agent      <->  Microsoft Graph  <->  SharePoint-Listen
        |
        +-> empfängt Windows-Sitzungsereignisse
        +-> protokolliert Logon/Reconnect/Disconnect/Logoff
        +-> verarbeitet erlaubte Adminbefehle
~~~

Die SharePoint-Verbindung ist keine Echtzeitsteuerung im Millisekundenbereich. Für das vorgesehene kleine Büro ist eine ereignisbasierte Aktualisierung mit sparsamen Hintergrundabfragen ausreichend.

---

## 3. Drei getrennte Zustandsdimensionen

Technischer Status, tatsächliche RDP-Sitzung und manuelles Flag dürfen nicht in einem einzigen Feld vermischt werden.

### Technischer Agentstatus

- online
- stale
- offline
- error

### Tatsächlicher Sitzungsstatus

- none
- logon
- connected
- reconnected
- disconnected
- logged_off

### Manuelles Flag

- none
- calculation_running
- maintenance
- blocked

Ein manuelles Flag enthält zusätzlich:

- Grund beziehungsweise Beschreibung;
- setzender Benutzer;
- Zeitpunkt;
- optionales Ablaufdatum;
- optional Projekt oder Vorgang.

Beispiele:

- Agent online, Sitzung getrennt, Flag „Berechnung läuft“;
- Agent online, Benutzer verbunden, kein Flag;
- Agent offline, letztes Flag „Wartung“, Status veraltet;
- Agent online, keine Sitzung, Flag „Gesperrt“.

Die UI berechnet daraus eine verständliche Gesamtanzeige, bewahrt aber die drei Originalzustände getrennt auf.

---

## 4. Manuelle Sperrlogik

Jeder berechtigte Benutzer darf für eine Workstation ein manuelles Flag setzen. Das genaue Rollenmodell ist konfigurierbar.

Bei calculation_running, maintenance oder blocked:

- normaler „Verbinden“-Button ist deaktiviert;
- Grund, Besitzer und Zeitpunkt werden sichtbar angezeigt;
- normale Benutzer können keinen Logoff auslösen;
- eine bestehende RDP-Sitzung darf bei calculation_running getrennt werden, weil ein Disconnect Programme normalerweise nicht beendet;
- ein Logoff wird blockiert, weil er Programme in der Sitzung beendet;
- Administratoren erhalten einen Override-Dialog;
- ein Override verlangt eine konkrete Begründung;
- Anfrage, Ergebnis und Begründung werden protokolliert.

Ein Benutzer darf ein selbst gesetztes Flag aufheben. Administratoren dürfen jedes Flag aufheben. Optional kann eingestellt werden, dass nur Admins Flags vom Typ maintenance und blocked ändern dürfen.

Das Flag wird ausschließlich manuell gesetzt und aufgehoben. Der Agent sucht nicht nach Berechnungsprogrammen und setzt das Flag nicht automatisch.

Wichtig: Die Sperre verhindert Aktionen innerhalb der Portal-App. Ein Benutzer mit direktem RDP-Zugriff kann die App technisch umgehen. Eine echte harte Durchsetzung erfordert später eingeschränkte Windows-RDP-Rechte, Firewallregeln oder ein RDP-Gateway. Unabhängig davon protokolliert der Workstation-Agent auch direkte RDP-Anmeldungen, soweit er aktiv ist.

---

## 5. Exaktes Sitzungs-Tracking

Der Windows-Agent ist für die tatsächlichen RDP-Ereignisse maßgeblich. Ein Klick auf „Verbinden“ ist noch kein erfolgreicher Login.

Zu erfassende Ereignisse:

- launch_requested – Benutzer hat in der App auf „Verbinden“ geklickt;
- rdp_logon – neue Remotedesktopsitzung wurde angemeldet;
- rdp_reconnect – Verbindung zu vorhandener Sitzung wurde wiederhergestellt;
- rdp_disconnect – RDP-Verbindung wurde getrennt, Sitzung bleibt bestehen;
- rdp_logoff – Sitzung wurde vollständig abgemeldet;
- admin_disconnect_requested;
- admin_disconnect_completed oder failed;
- admin_logoff_requested;
- admin_logoff_completed oder failed;
- manual_flag_set;
- manual_flag_cleared;
- admin_override.

Für jedes Ereignis soweit verfügbar speichern:

~~~text
event_id
timestamp_utc
event_type
workstation_id
workstation_hostname
windows_session_id
session_user_upn
session_user_domain
client_name
client_ip
actor_entra_object_id
actor_upn
result
reason
source
correlation_id
agent_version
~~~

Für die UI sind insbesondere diese Zeiträume zu bilden:

- erste Anmeldung;
- verbundene Zeit;
- getrennte, aber weiterhin bestehende Sitzung;
- Wiederverbindungen;
- endgültige Abmeldung;
- Gesamtdauer der Sitzung.

Disconnect und Logoff müssen im Datenmodell und in der UI konsequent unterschieden werden.

### Technische Erfassung

Der Agent soll bevorzugt Windows-Sitzungsbenachrichtigungen und WTS-APIs verwenden:

- SERVICE_CONTROL_SESSIONCHANGE;
- WTS Session Logon/Logoff;
- Remote Connect/Disconnect;
- WTSQuerySessionInformation für Benutzer, Client und Zustand.

Windows-Ereignisprotokolle dürfen ergänzend zur Validierung oder Wiederherstellung verwendet werden. Die primäre Implementierung darf nicht nur sprachabhängige Textausgaben von quser parsen.

Bei fehlender SharePoint-Verbindung speichert der Agent Ereignisse lokal in einer kleinen SQLite-Outbox. Nach Wiederherstellung werden sie idempotent anhand von event_id synchronisiert.

---

## 6. Start von mstsc.exe

Die lokale Portal-App liest das RDP-Profil der Workstation aus SharePoint, validiert es, schreibt eine temporäre .rdp-Datei und startet:

~~~text
mstsc.exe <temporäre-datei.rdp>
~~~

Zulässige hinterlegte Daten:

- Anzeigename;
- Hostname oder FQDN;
- Standort;
- Benutzername/UPN als Hinweis;
- Entra-SSO aktiviert/deaktiviert;
- RD-Gateway, falls später verwendet;
- Bildschirmmodus und Auflösung;
- Mehrmonitorbetrieb;
- Zwischenablage;
- lokale Laufwerke, Drucker und Audioumleitung;
- optionale Beschreibung.

Nicht hinterlegen:

- Klartextpasswort;
- Passwort in SharePoint;
- Passwort in einer .rdp-Datei;
- globale Adminzugangsdaten;
- frei zusammensetzbare Befehlszeilen.

Für Entra-RDP ist der Computername/FQDN zu verwenden und, soweit für die Umgebung erforderlich, enablerdsaadauth:i:1. Eine reine IP-Adresse darf dafür nicht vorausgesetzt werden.

Alle SharePoint-Werte müssen vor Verwendung über eine Allowlist validiert werden. Insbesondere dürfen Hostname, Gateway und RDP-Optionen keine zusätzlichen Zeilen oder frei eingeschleusten Parameter enthalten.

Die Portal-App protokolliert den Startwunsch. Ob die Verbindung tatsächlich zustande kam, wird ausschließlich durch ein späteres Agent-Ereignis bestätigt.

---

## 7. SharePoint-Listen

Verwende echte Microsoft-/SharePoint-Listen, keine Flag-Dateien.

### RDP_Workstations

Ein Element pro Workstation:

~~~text
WorkstationId
DisplayName
Hostname
Fqdn
Site
Description
Enabled
AllowedEntraGroupIds
UsernameHint
EntraSsoEnabled
GatewayHostname
UseAllMonitors
RedirectClipboard
RedirectDrives
RedirectPrinters
ManualFlag
ManualFlagReason
ManualFlagProject
ManualFlagSetByObjectId
ManualFlagSetByUpn
ManualFlagSetAtUtc
ManualFlagExpiresAtUtc
AgentStatus
AgentLastSeenUtc
AgentVersion
CurrentSessionState
CurrentSessionUser
CurrentWindowsSessionId
LastSessionEventUtc
~~~

### RDP_SessionEvents

Append-only Ereignisliste gemäß Abschnitt 5. EventId muss eindeutig sein.

### RDP_AdminCommands

~~~text
CommandId
TargetWorkstationId
TargetWindowsSessionId
CommandType
RequestedByObjectId
RequestedByUpn
RequestedAtUtc
ExpiresAtUtc
Reason
Status
ExecutedAtUtc
ResultMessage
~~~

Erlaubte CommandType-Werte:

- refresh_status;
- disconnect_session;
- logoff_session;
- clear_manual_flag.

Keine beliebigen PowerShell-, CMD- oder Shellbefehle zulassen.

### RDP_AccessRules

Optional für den MVP:

~~~text
RuleId
EntraUserOrGroupId
WorkstationId
MayConnect
MaySetCalculationFlag
ValidFromUtc
ValidUntilUtc
Enabled
~~~

### Konkurrenzschutz

Änderungen an einem Workstation-Flag verwenden das vorhandene ETag und If-Match. Bei 412 Precondition Failed muss die App neu laden und anzeigen, dass ein anderer Benutzer den Status zwischenzeitlich geändert hat. Ein vorhandenes Flag darf niemals still überschrieben werden.

### Wachstum der Ereignisliste

- häufig gefilterte Felder indizieren: Zeit, Workstation, Benutzer, Ereignistyp;
- Ansichten immer filtern und paginieren;
- konfigurierbare Aufbewahrung;
- Export als CSV/JSON;
- optional jährliche Archivlisten.

---

## 8. Anmeldung und Berechtigungen

### Lokale Portal-App

- MSAL-Public-Client-Anmeldung mit dem angemeldeten Entra-Benutzer;
- bevorzugt Broker/WAM, sofern in der Python-Umgebung stabil unterstützt;
- ansonsten Authorization Code Flow mit localhost redirect;
- Token-Cache im geschützten Benutzerkontext;
- keine Benutzerpasswörter selbst verarbeiten;
- Rollen aus Entra-Sicherheitsgruppen ableiten.

Vorgesehene Gruppen:

- RDP Portal Users;
- RDP Portal Admins.

### Workstation-Agent

- app-only Microsoft-Graph-Zugriff;
- zertifikatbasierte Anmeldung statt Client-Secret;
- Berechtigungen auf die benötigten SharePoint-Listen begrenzen;
- Zertifikat im Windows-Zertifikatsspeicher;
- privater Schlüssel nur für das Dienstkonto lesbar;
- lokale Konfiguration enthält nur IDs und keine Klartextgeheimnisse.

Der Agent darf Adminbefehle nur verarbeiten, wenn:

- Befehl für seine eigene Workstation bestimmt ist;
- Befehl noch nicht abgelaufen ist;
- Befehlstyp auf der Allowlist steht;
- Ersteller tatsächlich zur Admin-Gruppe gehört;
- Befehl noch nicht ausgeführt wurde;
- Session-ID zum erwarteten Ziel passt.

Alle Befehle müssen idempotent sein und ein Ergebnis zurückschreiben.

---

## 9. Rollen und Adminfunktionen

### Benutzer

- Workstations sehen;
- erlaubte Workstations verbinden;
- tatsächliche Sitzungsinformationen sehen, soweit freigegeben;
- manuelles Flag „Berechnung läuft“ setzen;
- eigenes Flag aufheben;
- keine fremde Sitzung abmelden;
- keine RDP-Profile oder Rechte bearbeiten.

### Administrator

- Workstations und RDP-Profile anlegen und bearbeiten;
- Entra-Gruppen und Zugriffsregeln zuordnen;
- alle Flags setzen und aufheben;
- Sitzungen trennen;
- Sitzungen nach Warnung abmelden;
- Sperrstatus mit dokumentierter Begründung überschreiben;
- Agentstatus und Synchronisationsfehler sehen;
- Logs filtern und exportieren;
- fehlerhafte oder abgelaufene Adminbefehle untersuchen.

### Kritische Adminaktionen

Für logoff_session und Override:

1. aktuelle Sitzung und Flag erneut aus SharePoint laden;
2. Warnung mit Benutzer, Workstation und Flaggrund anzeigen;
3. Begründung verlangen;
4. Adminbefehl mit kurzer Ablaufzeit erzeugen;
5. Anfrage als Audit-Ereignis protokollieren;
6. Agent führt aus und schreibt Erfolg oder Fehler;
7. UI zeigt erst nach Agentbestätigung „ausgeführt“.

---

## 10. Ausfall- und Sicherheitsverhalten

Wenn SharePoint oder Microsoft Graph nicht erreichbar ist:

- bestehende manuelle Sperre lokal beibehalten;
- keine neue Adminaktion ausführen;
- neue Ereignisse lokal puffern;
- bei neuen Verbindungen konservativ warnen;
- niemals ein Flag automatisch löschen;
- Status als „Daten möglicherweise veraltet“ anzeigen.

Weitere Regeln:

- RDP niemals direkt ins Internet freigeben;
- Nutzung nur intern, über FortiGate Site-to-Site oder Client-VPN;
- keine Passwörter in SharePoint, Logs oder Konfigurationsdateien;
- keine frei ausführbaren Remote-Befehle;
- Logs dürfen in der normalen UI nicht verändert oder gelöscht werden;
- lokale Logdateien ohne Zugangstoken und personenbezogene Daten auf das notwendige Maß begrenzen;
- direkte RDP-Umgehung als bekannte Grenze dokumentieren;
- Adminrechte nicht allein aus einem editierbaren SharePoint-Feld ableiten.

---

## 11. Empfohlener Python-Stack

### Lokale Anwendung

- Python 3.12+;
- PySide6;
- MSAL Python;
- Microsoft Graph über klar gekapselten HTTP-Client;
- Pydantic für Konfiguration und Datenmodelle;
- subprocess.Popen mit Argumentliste zum sicheren Start von mstsc.exe;
- PyInstaller für signierbare EXE/MSI-Ausgabe;
- Verteilung über Intune.

### Windows-Agent

- Python 3.12+;
- pywin32 und/oder ctypes;
- Windows Service;
- WTS-API;
- lokale SQLite-Outbox;
- strukturierte JSON-Logs;
- PyInstaller;
- eigene Graph-App-Registrierung mit Zertifikat.

### Qualität

- pytest;
- Ruff;
- mypy oder pyright für kritische Module;
- Windows-API-Adapter mit Mockimplementierung;
- Tests für ETag-Konflikte;
- Tests für Rollen und Adminbefehle;
- Tests für RDP-Datei-Injection;
- Tests für Logon/Disconnect/Reconnect/Logoff;
- Tests für Offline-Outbox und idempotente Synchronisation;
- UI-Screenshots und visuelle Prüfung.

---

## 12. Projektstruktur

~~~text
kirschke-rdp-portal/
  portal_app/
    app.py
    auth/
    graph/
    models/
    services/
    rdp/
    ui/
    design/
    assets/
  workstation_agent/
    service.py
    wts/
    eventlog/
    graph/
    commands/
    outbox/
  shared/
    schemas/
    enums/
    validation/
    logging/
  tests/
    unit/
    integration/
    windows/
  deployment/
    intune/
    agent/
    certificates/
  docs/
  pyproject.toml
  README.md
  .env.example
~~~

Gemeinsame Schemas und Enum-Werte müssen zwischen Portal-App und Agent identisch verwendet werden.

---

## 13. UI-Struktur

### Workstation-Übersicht

- Kirschke-Header mit Original-Logo und Produktname WORKSTATION CONTROL;
- flache, präzise Übersicht statt generischer SaaS-Kartenwand;
- Workstation, Standort, technischer Status, aktueller Benutzer und manuelles Flag;
- letzte tatsächliche Sitzung;
- primäre Aktion Verbinden;
- Aktionen Flag setzen, Details und für Admins Verwalten;
- Filter nach Standort, Flag, Benutzer und Agentstatus.

### Workstation-Detail

- hinterlegte RDP-Verbindungsdaten;
- technischer Agentstatus;
- aktueller Sitzungszustand;
- manuelles Flag mit Grund und Eigentümer;
- chronologische Sitzungshistorie;
- Verbinden, Flag setzen/aufheben;
- Admin: Trennen, Abmelden, Profil bearbeiten.

### Sitzungslog

- Benutzer;
- Workstation;
- Login;
- Disconnects und Reconnects;
- endgültiger Logoff;
- verbundene Dauer;
- Gesamtdauer;
- Ereignisquelle;
- Filter und CSV/JSON-Export.

### Administration

- Workstation-Stammdaten;
- RDP-Profile;
- Gruppen-/Rechtezuordnung;
- Agentstatus;
- offene und abgeschlossene Adminbefehle;
- Audit-Ereignisse;
- Aufbewahrung und Export.

---

## 14. Kirschke Corporate Design

Verwende Kirschke_Corporate_Design_Masterprompt.md und die originalen Kirschke-Assets als verbindliche Grundlage.

Zentrale Tokens:

~~~yaml
brand:
  blue: "#668BB0"
  charcoal: "#231F20"
  green: "#778C77"
  light_blue: "#80A3CA"

neutral:
  background: "#F4F5F2"
  paper: "#F7F7F3"
  surface: "#FFFFFF"
  surface_alt: "#E8ECE8"
  border: "#CDD3CD"
  text: "#151515"
  text_muted: "#606862"

interaction:
  focus: "#1F5F99"
  hover: "#91B2D6"
  active: "#6F91B8"

status:
  success: "#3F6F4B"
  warning: "#8A611F"
  error: "#9B2F2F"
  info: "#1F5F99"
~~~

Gestaltungsregeln:

- technisch präzise, sachlich, robust und modern;
- Website https://prof-kirschke.de/ als Referenz für Gesamtwirkung und Weißraum;
- GT America nur bei vorhandener Lizenz; sonst Inter, Segoe UI, Arial oder Helvetica;
- Original-Logo nicht nachzeichnen, verzerren oder umfärben;
- klare Achsen, feine Linien, rechteckige Flächen und sparsame 45-Grad-Einschnitte;
- keine Glassmorphism-, Gaming-, Banking- oder generische SaaS-Ästhetik;
- keine Pill-Buttons;
- Status nie ausschließlich über Farbe vermitteln;
- sichtbare Fokus-, Hover-, Aktiv-, Fehler- und Deaktiviert-Zustände;
- keine verstreuten Hexwerte außerhalb des zentralen Designsystems;
- High-DPI, Tastaturbedienung und WCAG-AA-Kontraste prüfen.

---

## 15. Umsetzung in Phasen

### Phase 1 – Lokaler UI-MVP

- PySide6-Projekt;
- Kirschke-Designsystem;
- lokale Demo-Daten;
- Workstation-Übersicht und Detailansicht;
- validierte .rdp-Erzeugung;
- Start von mstsc.exe;
- manuelle Flags;
- Rollen- und Adminoberflächen mit Mockdaten.

### Phase 2 – SharePoint und Entra

- Entra-Anmeldung;
- Graph-Client;
- SharePoint-Listen;
- ETag-Konfliktschutz;
- Workstation- und Flag-Synchronisation;
- Launch-Audit.

### Phase 3 – Tatsächliches Sitzungs-Tracking

- Windows-Agent;
- WTS-Sitzungsereignisse;
- Session-ID und Benutzer;
- Logon/Reconnect/Disconnect/Logoff;
- lokale SQLite-Outbox;
- idempotente SharePoint-Synchronisation.

### Phase 4 – Adminaktionen

- AdminCommand-Liste;
- Agent-Polling mit Backoff;
- Trennen und Logoff;
- Override mit Begründung;
- Ergebnisbestätigung;
- Audit-Export;
- Intune-Paketierung und Signierung.

---

# Copy-and-paste-Prompt für Codex oder Claude

~~~text
Du bist Senior Python-Entwickler, Windows-Systementwickler, Security Engineer und UX/UI-Designer für technische Unternehmensanwendungen.

Entwickle das Projekt „Kirschke RDP Workstation Portal“ als lokale Windows-Anwendung ohne eigenen dauerhaft laufenden Portalserver.

## Verbindliches Ziel

Die Anwendung verwaltet Büro-Workstations und erfüllt genau diese Kernaufgaben:

1. Workstations mit hinterlegten RDP-Verbindungsdaten anzeigen.
2. Per Klick eine validierte lokale .rdp-Datei erzeugen und mstsc.exe starten.
3. Tatsächliche RDP-Anmeldung, Wiederverbindung, Trennung und endgültige Abmeldung protokollieren.
4. Anzeigen, wer wann auf welcher Workstation verbunden beziehungsweise angemeldet war.
5. Manuelle Flags „Berechnung läuft“, „Wartung“ und „Gesperrt“ setzen und aufheben.
6. Bei aktivem Flag normale Verbindungs- und Logoff-Aktionen in der Anwendung blockieren.
7. Admins Trennen, Logoff, Flag-Aufhebung und Override mit Begründung ermöglichen.
8. Workstation-Daten, Flags, Adminbefehle und Logs in SharePoint-Listen speichern.
9. Entra ID für Benutzeridentität und Rollen verwenden.

Automatische Berechnungserkennung ist ausdrücklich ausgeschlossen. Prüfe weder CPU/GPU noch Prozesse und implementiere keine CalculationJob-Erkennung. Das Flag „Berechnung läuft“ wird ausschließlich manuell gesetzt und aufgehoben.

## Architektur

Implementiere:

- lokale PySide6-Portal-App auf Benutzer- und Admin-PCs;
- Python-Windows-Agent als Dienst auf jeder verwalteten Workstation;
- SharePoint-Listen als zentrale Datenablage;
- Microsoft Graph als Zugriffsschicht;
- Microsoft Entra ID / MSAL für Anmeldung;
- mstsc.exe für die eigentliche RDP-Verbindung.

Kein FastAPI-Webportal, kein PostgreSQL-Server und kein eigener dauerhaft laufender Portal-PC.

## Technologiestack

- Python 3.12+;
- PySide6;
- MSAL Python;
- Microsoft Graph;
- Pydantic;
- pywin32 und/oder ctypes für WTS;
- SQLite nur als lokale Agent-Outbox;
- PyInstaller;
- pytest, Ruff und Typprüfung;
- Intune-Paketierung vorbereiten.

Windows-spezifische APIs müssen hinter Adaptern liegen, damit Kernlogik und Tests auch ohne Windows ausführbar sind.

## Zustände

Halte drei Dimensionen getrennt:

1. AgentStatus: online, stale, offline, error.
2. SessionState: none, logon, connected, reconnected, disconnected, logged_off.
3. ManualFlag: none, calculation_running, maintenance, blocked.

ManualFlag enthält Grund, Projekt optional, setzenden Benutzer, Zeitpunkt und optionales Ablaufdatum.

## Manuelle Sperre

Bei calculation_running, maintenance oder blocked:

- Verbinden in der normalen UI deaktivieren;
- Grund, Besitzer und Zeitpunkt anzeigen;
- Logoff für normale Benutzer blockieren;
- Disconnect bei calculation_running weiterhin erlauben;
- Admin-Override nur nach erneuter Zustandsprüfung, deutlicher Warnung und Pflichtbegründung;
- Anfrage und Ergebnis vollständig protokollieren.

Das Flag darf niemals anhand eines Prozesses automatisch gesetzt oder gelöscht werden.

Dokumentiere klar, dass die UI-Sperre direkten manuellen Aufruf von mstsc.exe nicht technisch verhindert. Der Agent protokolliert auch direkte RDP-Sitzungen. Eine harte Durchsetzung über Gateway, Firewall oder dynamische Windows-Rechte gehört nicht in den MVP.

## Tatsächliches RDP-Tracking

Der Workstation-Agent ist die maßgebliche Quelle. Erfasse:

- launch_requested;
- rdp_logon;
- rdp_reconnect;
- rdp_disconnect;
- rdp_logoff;
- admin_disconnect_requested/completed/failed;
- admin_logoff_requested/completed/failed;
- manual_flag_set/cleared;
- admin_override.

Verwende bevorzugt SERVICE_CONTROL_SESSIONCHANGE, WTS Session Events und WTSQuerySessionInformation. Unterscheide Disconnect und Logoff überall konsequent.

Speichere soweit verfügbar:

- UTC-Zeit;
- Workstation;
- Windows-Session-ID;
- Benutzer-UPN/Domain;
- Clientname und Client-IP;
- Eventtyp;
- Ergebnis;
- Akteur bei Portal-/Adminaktionen;
- Grund;
- Event-ID und Correlation-ID;
- Quelle und Agent-Version.

Wenn SharePoint nicht erreichbar ist, speichere Ereignisse in einer lokalen SQLite-Outbox und synchronisiere sie später idempotent über eine eindeutige Event-ID.

## SharePoint-Listen

Erstelle beziehungsweise dokumentiere:

1. RDP_Workstations
   - Stammdaten, RDP-Profil, manuelles Flag, Agentstatus und aktuelle Sitzung.
2. RDP_SessionEvents
   - append-only Ereignisse.
3. RDP_AdminCommands
   - refresh_status, disconnect_session, logoff_session, clear_manual_flag.
4. RDP_AccessRules
   - optional Benutzer-/Gruppen- und Zielzuordnung.

Verwende ETags und If-Match für Flagänderungen. Bei HTTP 412 neu laden und einen verständlichen Konflikt anzeigen. Überschreibe niemals still den Status eines anderen Benutzers.

Der Agent darf keine beliebigen Shell-, CMD- oder PowerShell-Befehle ausführen. Adminbefehle sind streng typisiert, kurzlebig, idempotent und an Workstation sowie Session-ID gebunden.

## Authentifizierung

Portal-App:

- MSAL Public Client;
- interaktive Anmeldung und sicherer Token-Cache;
- bevorzugt Broker/WAM, sonst localhost redirect;
- Rollen aus Entra-Sicherheitsgruppen;
- keine Passwortverarbeitung.

Agent:

- app-only Zugriff mit Zertifikat;
- nur notwendige SharePoint-Listen;
- Zertifikat im Windows-Zertifikatsspeicher;
- privater Schlüssel nur für das Dienstkonto;
- keine Client-Secrets im Code.

Gruppen:

- RDP Portal Users;
- RDP Portal Admins.

Adminrechte niemals aus einem editierbaren SharePoint-Feld allein ableiten.

## mstsc.exe

Lies ein validiertes RDP-Profil aus RDP_Workstations, schreibe eine temporäre .rdp-Datei und starte mstsc.exe über subprocess.Popen mit Argumentliste.

Erlaubte Profilfelder:

- Hostname/FQDN;
- Username-Hinweis;
- Entra-SSO;
- optional RD-Gateway;
- Bildschirm/Mehrmonitor;
- Zwischenablage;
- Laufwerke, Drucker, Audio.

Keine Passwörter speichern. Keine frei übergebenen RDP-Zeilen erlauben. Hostname, Gateway und alle Optionen strikt validieren, damit kein SharePoint-Wert zusätzliche RDP-Parameter einschleusen kann.

Für Entra-RDP Computername/FQDN und bei Bedarf enablerdsaadauth:i:1 verwenden. Der Klick wird als launch_requested protokolliert; eine erfolgreiche Verbindung wird erst durch den Agent bestätigt.

## Rollen und UI

Benutzer:

- Workstations ansehen und verbinden;
- manuelles Flag „Berechnung läuft“ setzen;
- eigenes Flag aufheben;
- keine fremde Sitzung abmelden.

Admins:

- Workstations und RDP-Profile verwalten;
- alle Flags setzen/aufheben;
- Sitzungen trennen;
- nach Warnung und Begründung Logoff auslösen;
- Overrides durchführen;
- Agentstatus prüfen;
- Logs filtern und als CSV/JSON exportieren.

UI-Seiten:

1. Workstation-Übersicht.
2. Workstation-Detail mit RDP-Profil, Session, Flag und Timeline.
3. Sitzungslog mit Login, Reconnect, Disconnect und Logoff.
4. Administration für Profile, Gruppen, Agenten und Befehle.
5. Audit- und Exportansicht.

## Kirschke Corporate Design

Lies zuerst Kirschke_Corporate_Design_Masterprompt.md und verwende die originalen Kirschke-Assets.

Zentrale Farben:

- #668BB0 Markenblau;
- #231F20 Anthrazit;
- #778C77 Grün;
- #80A3CA Hellblau;
- #F4F5F2 Hintergrund;
- #FFFFFF Oberfläche;
- #151515 Text;
- #CDD3CD Rahmen;
- #1F5F99 Fokus/Info;
- #3F6F4B Erfolg;
- #8A611F Warnung;
- #9B2F2F Fehler.

Die UI wirkt technisch präzise, sachlich, robust und modern. Klare Achsen, Weißraum, feine Linien, rechteckige Flächen und sparsame 45-Grad-Einschnitte. Keine generische SaaS-Optik, kein Glassmorphism und keine Pill-Buttons. Original-Logos nicht verändern. GT America nur mit lizenzierter Datei, sonst Inter, Segoe UI, Arial oder Helvetica. Tokens zentral halten. Tastaturbedienung, High-DPI, Fokuszustände und WCAG-AA prüfen.

## Ausfallverhalten

Bei SharePoint-/Graph-Ausfall:

- bestehende Flags lokal beibehalten;
- keine Adminbefehle ausführen;
- Events in Outbox puffern;
- Status als möglicherweise veraltet anzeigen;
- niemals Flag automatisch löschen;
- keine Aktion fälschlich als erfolgreich melden.

## Vorgehen

1. Repository und Kirschke-Assets inventarisieren.
2. Architektur, SharePoint-Schema und Berechtigungen dokumentieren.
3. Gemeinsame Enums und Pydantic-Schemas anlegen.
4. PySide6-MVP mit Mockdaten und Kirschke-Design bauen.
5. Sichere RDP-Profilvalidierung und mstsc-Start implementieren.
6. Entra/MSAL und Graph integrieren.
7. SharePoint-Listen und ETag-Konflikte implementieren.
8. Windows-Agent und WTS-Events implementieren.
9. Offline-Outbox und idempotente Synchronisation implementieren.
10. Adminbefehle, Warnungen, Pflichtbegründung und Ergebnisbestätigung implementieren.
11. Tests, visuelle Prüfung, PyInstaller und Intune-Dokumentation ergänzen.

## Abnahmekriterien

- kein eigener Portalserver erforderlich;
- lokale Anwendung startet reproduzierbar;
- Entra-Anmeldung und Rollen funktionieren;
- RDP-Profile enthalten keine Passwörter;
- mstsc.exe wird mit validierten Daten gestartet;
- launch_requested und tatsächliche Sitzung werden getrennt protokolliert;
- Logon, Reconnect, Disconnect und Logoff sind unterscheidbar;
- direkte RDP-Anmeldungen werden vom Agent erkannt;
- „Berechnung läuft“ wird ausschließlich manuell gesetzt;
- aktives Flag blockiert normale Logoff-Aktionen in der App;
- Admin-Override verlangt eine Begründung;
- Adminbefehl gilt erst nach Agentbestätigung als erfolgreich;
- Offline-Ereignisse werden später ohne Duplikate synchronisiert;
- ETag-Konflikte überschreiben keine fremden Änderungen;
- keine beliebigen Remote-Befehle möglich;
- Kirschke-Design-Tokens und Original-Logos werden korrekt eingesetzt;
- relevante Tests bestehen;
- README, SharePoint-Einrichtung, Entra-App-Registrierungen, Agent-Installation und Intune-Verteilung sind dokumentiert.

Beginne mit einer kurzen Bestandsaufnahme und einer konkreten Implementierungsreihenfolge. Implementiere anschließend Phase 1 vollständig. Beende die Arbeit nicht mit einem bloßen Mock-up oder einer Empfehlungsliste.
~~~

---

## 16. Bewusste Grenze

Diese Architektur benötigt keinen eigenen Dauer-PC. SharePoint Online ist die zentrale Datenbasis; nur die jeweilige lokale App und die eingeschalteten Workstations beziehungsweise deren Agenten sind aktiv.

Die Anwendung ist zunächst eine zuverlässige Bedien-, Koordinations- und Protokollierungsschicht. Ein manuelles Flag verhindert gefährliche Aktionen innerhalb der Anwendung. Es ist keine absolute Windows-Sicherheitsgrenze gegen lokale Administratoren oder direkten Start von mstsc.exe. Diese Trennung muss in UI und Dokumentation transparent bleiben.
