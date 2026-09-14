# Kirschke RDP Workstation Portal

**Version:** 0.2.12 (lokaler Pilot, Review vom 11.09.2026)

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
Die vorhandenen Entra-/Graph-/Windows-Dienst-Module sind noch keine integrierte Betriebsvariante.
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
Der lokale Adminzugang wird beim ersten Öffnen eingerichtet; es gibt kein Standardpasswort.
Nach fünf Fehlversuchen ist er 15 Minuten gesperrt. **Reichweite dieses Schutzes:** Der
Passwort-Hash liegt im Profil des angemeldeten Benutzers, der ihn löschen und damit die
Ersteinrichtung erneut auslösen kann. Der Adminbereich trennt Rollen in der Oberfläche
und hält beiläufige Änderungen aus dem gemeinsamen Inventar heraus; eine Grenze gegen die
Person am Gerät ist er nicht. Die wirksamen Kontrollen setzt Windows: die Freigabe-ACL auf
dem gemeinsamen Speicher, im AD-Modus die Gruppe `RDP-Portal-Admins`, und für eine
administrative Abmeldung echte Administrator-Anmeldedaten des Zielrechners.
Im optionalen AD-Modus ist der lokale Passwort-Fallback standardmäßig ausgeschaltet.
Programmlogs liegen unter `%LOCALAPPDATA%\KirschkeRDPPortal\logs\portal.log` und werden rotiert.

Vorprüfung ohne RDP-Anmeldung oder Datenänderung:

```powershell
python -m portal_app.preflight --storage "C:\Pilot\RDP-Portal" --json
```

Für parallele Schreibzugriffe denselben SMB-Ordner verwenden. OneDrive-Replikate bieten keine
verteilte Transaktionssperre; dort zunächst nur eine schreibende Portalinstanz betreiben.

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
│   ├── graph/           # Microsoft Graph client (Phase 2)
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

### Phase 2: SharePoint and Entra Integration
- [ ] Microsoft Entra ID authentication (MSAL)
- [ ] Microsoft Graph API client
- [ ] SharePoint list integration
- [ ] ETag concurrency control
- [ ] Data synchronization
- [ ] Launch event auditing

### Phase 3: Windows Agent
- [ ] Windows service
- [x] WTS-API integration for session tracking
- [x] Event detection (Logon, Reconnect, Disconnect, Logoff)
- [ ] Local SQLite outbox for offline events
- [ ] Idempotent synchronization

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
RDP-Sitzungszustand eines Ziel-PCs an den gemeinsamen Portalordner. Build, Installation und die Grenzen des
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

# SharePoint
SHAREPOINT_SITE_ID=your-site-id
SHAREPOINT_WORKSTATIONS_LIST=RDP_Workstations
SHAREPOINT_SESSIONS_LIST=RDP_SessionEvents
SHAREPOINT_COMMANDS_LIST=RDP_AdminCommands

# Agent
AGENT_POLL_INTERVAL=30
AGENT_CERT_THUMBPRINT=your-cert-thumbprint
```

See `.env.example` for all available options.

## Corporate Design

The application uses the Kirschke Corporate Design system as specified in the project requirements:

- **Brand Colors:** #668BB0 (Blue), #231F20 (Charcoal), #778C77 (Green), #80A3CA (Light Blue)
- **Neutral Colors:** #F4F5F2 (Background), #F7F7F3 (Paper), #FFFFFF (Surface)
- **Typography:** Segoe UI (fallback to Inter, Arial, Helvetica)
- **Spacing:** Consistent spacing system (2px, 4px, 8px, 16px, 24px, 32px, etc.)

## Security Notes

- No passwords are stored in the application or configuration. The local admin
  password is kept only as a PBKDF2-HMAC-SHA256 hash (310 000 iterations, random
  16-byte salt) and is rate-limited to five attempts per 15 minutes. See the
  scope note under "Der lokale Adminzugang" above for what that gate does and
  does not protect.
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
- Agent snapshots read from an SMB share are untrusted input and are bounded in
  file size, file count, list length and field length.
- Signing out a session requires a fresh agent reply with matching session ID,
  user and logon time, a request no older than 30 seconds, an unused request ID,
  and either proven session ownership or real administrator credentials for the
  target computer. Note the UAC caveat in
  [docs/no-ad-pilotbetrieb.md](docs/no-ad-pilotbetrieb.md) for local accounts.
- Admin actions require explicit confirmation and reasoning.
- Roughly 5 700 lines of Entra/Graph/SharePoint code ship but are **not
  integrated and untested**; one known defect makes the token cache inoperable.
  See [docs/phase2-status.md](docs/phase2-status.md) before enabling any of it.

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
2. **No SharePoint integration** - Uses mock data
3. **Agent transport** - Statusdateien können über SMB oder einen synchronisierten Ordner gelesen werden. Vollständige Agent-Ereignisse werden noch nicht in das lokale Portal-Log übertragen.
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
