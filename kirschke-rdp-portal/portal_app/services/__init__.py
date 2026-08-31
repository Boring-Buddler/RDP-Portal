"""Services for Kirschke RDP Workstation Portal."""

# Services will be added in Phase 2 for SharePoint synchronization

from portal_app.services.mock_services import MockWorkstationService
from portal_app.services.local_store import LocalStore
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.directory_users import discover_windows_domain_accounts
from portal_app.services.active_directory_sync import ActiveDirectorySyncResult, sync_rdp_group_members
from portal_app.services.rdp_diagnostics import (
    RDPDiagnosticResult,
    clear_saved_rdp_credentials,
    run_rdp_diagnostics,
)

__all__ = [
    "MockWorkstationService",
    "LocalStore",
    "detect_initial_user",
    "discover_windows_domain_accounts",
    "ActiveDirectorySyncResult",
    "sync_rdp_group_members",
    "RDPDiagnosticResult",
    "clear_saved_rdp_credentials",
    "run_rdp_diagnostics",
]
