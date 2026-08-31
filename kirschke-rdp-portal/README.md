# Kirschke RDP Workstation Portal

**Version:** 0.1.0 (Phase 1 - Local UI MVP)

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

## Active Directory (optional)

Die Admin-Verwaltung kann gespeicherte RDP-Zugriffe nach Bestätigung mit AD-Gruppen
`RDP-<Maschinen-ID>` abgleichen. Die Vorbereitung auf einem Verwaltungsrechner ist in
[docs/active-directory-setup.md](docs/active-directory-setup.md) beschrieben.
Für die vollständige Pilotabnahme siehe auch
[docs/pilotbetrieb-anleitung.md](docs/pilotbetrieb-anleitung.md).

## Repository Hygiene

The repository contains source code, configuration examples, tests, and documentation only. Local environments,
Python/test caches, build output, and runtime logs are excluded through the root `.gitignore`. Recreate a local
environment with the installation commands above instead of committing it.

When a change affects setup, usage, configuration, or user-visible behavior, update this README concisely in the
same change.

## Running with Different User Roles

For testing admin features, you can modify the `app.py` file to use an admin user:

```python
# In RDPPortalApp.get_current_user():
# return MockUser.create_admin()  # For admin testing
# return MockUser.create_user()    # For regular user testing
```

## Configuration

### Environment Variables (Phase 2+)

Create a `.env` file for configuration:

```ini
# Entra ID
TENANT_ID=your-tenant-id
CLIENT_ID=your-client-id
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

- No passwords are stored in the application or configuration
- RDP profiles are validated to prevent injection attacks
- mstsc.exe is launched with explicit argument lists (no shell=True)
- All SharePoint values are validated before use
- Admin actions require explicit confirmation and reasoning

## Testing

```bash
# Run all tests
pytest

# Run specific tests
pytest tests/test_models.py
pytest tests/test_rdp.py

# With coverage
pytest --cov=portal_app --cov=shared
```

### Test the Windows agent locally

```powershell
# One-time live WTS diagnosis
python -m workstation_agent.service --status

# Publish a continuously refreshed status for a test machine
$env:WORKSTATION_ID="WS-001"
python -m workstation_agent.service --run
```

The portal reads this local test status automatically every five seconds. A snapshot is matched by
workstation ID or hostname. After 90 seconds without an update it is shown as stale and after five
minutes as offline. Set `AGENT_STATUS_DIR` in both processes when they should use a custom shared
test directory.

## Known Limitations (Phase 1)

1. **No actual authentication** - Uses mock users for development
2. **No SharePoint integration** - Uses mock data
3. **No remote agent transport yet** - The WTS agent detects real local sessions; sharing that status between separate workstations and the portal still requires the Phase 2 Microsoft Graph channel
4. **Local process monitoring only** - The portal detects the lifetime of RDP clients it started; closing mstsc.exe does not prove that the remote Windows session logged off
5. **Admin commands not executed** - Only shows confirmation dialogs

These will be addressed in subsequent phases.

## License

Proprietary - Kirschke

## Contact

For questions or issues, contact: it@prof-kirschke.de
