"""Session event logging and handling for Kirschke RDP Workstation Portal Agent."""

from workstation_agent.eventlog.handler import (
    EventLogConfig,
    AgentSessionEvent,
    EventQueue,
    SessionEventDetector,
    create_event_queue,
    create_session_event_detector,
)

__all__ = [
    "EventLogConfig",
    "AgentSessionEvent",
    "EventQueue",
    "SessionEventDetector",
    "create_event_queue",
    "create_session_event_detector",
]
