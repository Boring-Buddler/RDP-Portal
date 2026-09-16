# Kirschke RDP Workstation Portal

## Serverloser Projektplan und Copy-and-paste-Prompt für KI-Agenten

Version: 3.0  
Stand: 16.09.2026  
Aktuelle Portal-Version: 0.6.1 | Aktuelle Agent-Version: 1.5.0

---

**Änderungshistorie:**
- v3.0 (16.09.2026): Aktualisierung auf Version 0.6.1, neue Features integriert, Status der Phasen dokumentiert
- v2.0 (27.08.2026): Ursprüngliches Dokument

---

## 0. Aktueller Implementierungsstand (16.09.2026)

### Umgesetzte Phasen

#### Phase 1 – Lokaler UI-MVP: ✅ **ABGESCHLOSSEN**

- [x] PySide6-Projekt mit Kirschke-Designsystem
- [x] Workstation-Übersicht (Karten- und Tabellenansicht)
- [x] Workstation-Detailansicht mit allen Informationen
- [x] Validierte .rdp-Erzeugung mit Auflösungspresets
- [x] Start von mstsc.exe mit Prozessmonitoring
- [x] Manuelle Flags (Berechnung läuft, Wartung, Gesperrt)
- [x] Rollen- und Adminoberflächen mit lokalem JSON-Speicher
- [x] Sitzungsprotokollierung (Logon/Reconnect/Disconnect/Logoff)
- [x] Live-Status-Polling (2-60 Sekunden konfigurierbar)
- [x] Agent-Zuordnung und Identitätsauflösung
- [x] Sitzungsübernahme für Console-Sessions
- [x] Diagnosetools (Ping, ipconfig, Agent-Statusinspektion)
- [x] Per-Maschine Fallback-Ordner für Agenten-Statusdateien
- [x] 2K/4K Auflösungsunterstützung bis Bildschirmgröße
- [x] Eigene Ruhesitzung blau/orange gestrichelt

#### Phase 2 – SharePoint und Entra: ⚠️ **TEILWEISE IMPLEMENTIERT**

- [ ] Entra-Anmeldung (MSAL integriert, aber nicht aktiviert)
- [ ] Graph-Client (vorhanden, aber nicht integriert)
- [ ] SharePoint-Listen (Schema definiert, aber lokaler Speicher aktiv)
- [ ] ETag-Konfliktschutz (für zukünftige SharePoint-Integration vorbereitet)
- [ ] Workstation- und Flag-Synchronisation
- [ ] Launch-Audit

**Status:** Code für Phase 2 existiert (~5700 Zeilen), ist aber **nicht integriert und ungetestet**. Siehe [docs/phase2-status.md](../kirschke-rdp-portal/docs/phase2-status.md)

#### Phase 3 – Tatsächliches Sitzungs-Tracking: ✅ **ABGESCHLOSSEN**

- [x] Windows-Agent als Dienst
- [x] WTS-Sitzungsereignisse (Logon/Reconnect/Disconnect/Logoff)
- [x] Session-ID und Benutzer-Identifikation
- [x] Agent-Statuskanal mit SDDL-Sicherheit
- [x] SQLite-Outbox für Offline-Ereignisse
- [x] Idempotente Synchronisation
- [x] Reservierungssynchronisation zwischen Agenten

#### Phase 4 – Adminaktionen: ✅ **ABGESCHLOSSEN**

- [x] AdminCommand-Liste (lokal implementiert)
- [x] Agent-Polling mit Backoff
- [x] Sitzungen trennen und abmelden (über Agenten-Statuskanal)
- [x] Override mit Begründung und Bestätigung
- [x] Ergebnisbestätigung durch Agenten
- [x] Audit-Export (CSV/JSON)
- [ ] Intune-Paketierung (vorbereitet, aber nicht finalisiert)

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

~~~

---

## 16. Bewusste Grenze

Diese Architektur benötigt keinen eigenen Dauer-PC. SharePoint Online ist die zentrale Datenbasis; nur die jeweilige lokale App und die eingeschalteten Workstations beziehungsweise deren Agenten sind aktiv.

Die Anwendung ist zunächst eine zuverlässige Bedien-, Koordinations- und Protokollierungsschicht. Ein manuelles Flag verhindert gefährliche Aktionen innerhalb der Anwendung. Es ist keine absolute Windows-Sicherheitsgrenze gegen lokale Administratoren oder direkten Start von mstsc.exe. Diese Trennung muss in UI und Dokumentation transparent bleiben.
