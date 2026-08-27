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
- [x] Mock data for development
- [x] User roles (User vs Admin)

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
- [ ] WTS-API integration for session tracking
- [ ] Event detection (Logon, Reconnect, Disconnect, Logoff)
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
- [ ] PyInstaller packaging
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

## Known Limitations (Phase 1)

1. **No actual authentication** - Uses mock users for development
2. **No SharePoint integration** - Uses mock data
3. **No Windows agent** - Session tracking is simulated
4. **No actual RDP connection** - Only generates RDP files
5. **Admin commands not executed** - Only shows confirmation dialogs

These will be addressed in subsequent phases.

## License

Proprietary - Kirschke

## Contact

For questions or issues, contact: it@prof-kirschke.de
