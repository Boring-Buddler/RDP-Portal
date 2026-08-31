"""Enums for Kirschke RDP Workstation Portal.

These enums are used consistently across both the portal application
and the workstation agent to ensure type safety and consistency.
"""

from enum import Enum, auto
from typing import Final


class AgentStatus(str, Enum):
    """Technical status of the workstation agent."""
    
    ONLINE: Final = "online"
    STALE: Final = "stale"
    OFFLINE: Final = "offline"
    ERROR: Final = "error"


class SessionState(str, Enum):
    """Actual RDP session state on the workstation."""
    
    NONE: Final = "none"
    LOGON: Final = "logon"
    CONNECTED: Final = "connected"
    RECONNECTED: Final = "reconnected"
    DISCONNECTED: Final = "disconnected"
    LOGGED_OFF: Final = "logged_off"


class ConnectionTargetMode(str, Enum):
    """Address source used for the RDP connection."""

    AUTO: Final = "auto"
    IP_ADDRESS: Final = "ip_address"
    HOSTNAME: Final = "hostname"
    FQDN: Final = "fqdn"


class ManualFlagType(str, Enum):
    """Manual flag types that can be set by users or administrators."""
    
    NONE: Final = "none"
    CALCULATION_RUNNING: Final = "calculation_running"
    MAINTENANCE: Final = "maintenance"
    BLOCKED: Final = "blocked"


class EventType(str, Enum):
    """Types of session and system events."""
    
    # Portal-initiated events
    LAUNCH_REQUESTED: Final = "launch_requested"
    
    # Agent-detected RDP events
    RDP_LOGON: Final = "rdp_logon"
    RDP_RECONNECT: Final = "rdp_reconnect"
    RDP_DISCONNECT: Final = "rdp_disconnect"
    RDP_LOGOFF: Final = "rdp_logoff"
    
    # Admin command events
    ADMIN_DISCONNECT_REQUESTED: Final = "admin_disconnect_requested"
    ADMIN_DISCONNECT_COMPLETED: Final = "admin_disconnect_completed"
    ADMIN_DISCONNECT_FAILED: Final = "admin_disconnect_failed"
    ADMIN_LOGOFF_REQUESTED: Final = "admin_logoff_requested"
    ADMIN_LOGOFF_COMPLETED: Final = "admin_logoff_completed"
    ADMIN_LOGOFF_FAILED: Final = "admin_logoff_failed"
    RDP_ACCESS_GRANTED: Final = "rdp_access_granted"
    RDP_ACCESS_REVOKED: Final = "rdp_access_revoked"
    RDP_ACCESS_SYNC_COMPLETED: Final = "rdp_access_sync_completed"
    RDP_ACCESS_SYNC_FAILED: Final = "rdp_access_sync_failed"
    
    # Manual flag events
    MANUAL_FLAG_SET: Final = "manual_flag_set"
    MANUAL_FLAG_CLEARED: Final = "manual_flag_cleared"
    
    # Override events
    ADMIN_OVERRIDE: Final = "admin_override"


class CommandType(str, Enum):
    """Types of admin commands that can be executed by the agent."""
    
    REFRESH_STATUS: Final = "refresh_status"
    DISCONNECT_SESSION: Final = "disconnect_session"
    LOGOFF_SESSION: Final = "logoff_session"
    CLEAR_MANUAL_FLAG: Final = "clear_manual_flag"


class EventResult(str, Enum):
    """Result status for events."""
    
    SUCCESS: Final = "success"
    FAILED: Final = "failed"
    PENDING: Final = "pending"
    TIMEOUT: Final = "timeout"


class EventSource(str, Enum):
    """Source of the event."""
    
    PORTAL: Final = "portal"
    AGENT: Final = "agent"
    ADMIN: Final = "admin"
    SYSTEM: Final = "system"


# Command status values
class CommandStatus(str, Enum):
    """Status of an admin command."""
    
    PENDING: Final = "pending"
    EXECUTED: Final = "executed"
    FAILED: Final = "failed"
    EXPIRED: Final = "expired"


# User roles
class UserRole(str, Enum):
    """User roles in the system."""
    
    USER: Final = "user"
    ADMIN: Final = "admin"


__all__ = [
    "AgentStatus",
    "SessionState",
    "ConnectionTargetMode",
    "ManualFlagType",
    "EventType",
    "CommandType",
    "EventResult",
    "EventSource",
    "CommandStatus",
    "UserRole",
]
