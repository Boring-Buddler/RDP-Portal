"""Services for Kirschke RDP Workstation Portal."""

# Services will be added in Phase 2 for SharePoint synchronization

from portal_app.services.mock_services import MockWorkstationService
from portal_app.services.local_store import LocalStore
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.rdp_diagnostics import RDPDiagnosticResult, run_rdp_diagnostics

__all__ = [
    "MockWorkstationService",
    "LocalStore",
    "detect_initial_user",
    "RDPDiagnosticResult",
    "run_rdp_diagnostics",
]
