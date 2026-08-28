"""Shared modules for Kirschke RDP Workstation Portal.

This package contains common schemas, enums, validation logic, and utilities
used by both the portal application and the workstation agent.
"""

from shared.enums import (
    AgentStatus,
    CommandType,
    ConnectionTargetMode,
    EventType,
    ManualFlagType,
    SessionState,
)
from shared.schemas import (
    WorkstationSchema,
    SessionEventSchema,
    AdminCommandSchema,
    AccessRuleSchema,
    RDPProfileSchema,
    ManualFlagSchema,
)

__all__ = [
    # Enums
    "AgentStatus",
    "ManualFlagType",
    "SessionState",
    "EventType",
    "CommandType",
    "ConnectionTargetMode",
    # Schemas
    "WorkstationSchema",
    "SessionEventSchema",
    "AdminCommandSchema",
    "AccessRuleSchema",
    "RDPProfileSchema",
    "ManualFlagSchema",
]
