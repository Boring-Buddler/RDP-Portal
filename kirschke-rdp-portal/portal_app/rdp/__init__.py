"""RDP functionality for Kirschke RDP Workstation Portal."""

from portal_app.rdp.generator import RDPFileGenerator, RDPGenerationError, generate_rdp_file
from portal_app.rdp.launcher import (
    RDPSessionLauncher,
    TrackedRDPSession,
    cleanup_rdp_files,
    consume_finished_rdp_sessions,
    disconnect_rdp_session,
    get_active_rdp_sessions,
    has_active_rdp_session,
    launch_rdp_session,
    test_rdp_file,
)

__all__ = [
    "RDPFileGenerator",
    "RDPGenerationError",
    "RDPSessionLauncher",
    "generate_rdp_file",
    "launch_rdp_session",
    "test_rdp_file",
    "cleanup_rdp_files",
    "TrackedRDPSession",
    "get_active_rdp_sessions",
    "has_active_rdp_session",
    "consume_finished_rdp_sessions",
    "disconnect_rdp_session",
]
