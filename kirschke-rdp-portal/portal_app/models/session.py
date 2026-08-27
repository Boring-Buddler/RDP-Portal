"""Session and event models for Kirschke RDP Workstation Portal."""

from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
from shared.enums import EventType, EventResult, EventSource
from shared.schemas import SessionEventSchema
from shared.validation import generate_test_entra_id, generate_test_upn, generate_test_hostname


@dataclass
class SessionEvent:
    """A session event recorded by the system."""
    
    event_id: str
    timestamp_utc: datetime
    event_type: EventType
    workstation_id: str
    workstation_hostname: Optional[str] = None
    windows_session_id: Optional[int] = None
    session_user_upn: Optional[str] = None
    session_user_domain: Optional[str] = None
    client_name: Optional[str] = None
    client_ip: Optional[str] = None
    actor_entra_object_id: Optional[str] = None
    actor_upn: Optional[str] = None
    result: Optional[EventResult] = None
    reason: Optional[str] = None
    source: EventSource = EventSource.PORTAL
    correlation_id: Optional[str] = None
    agent_version: Optional[str] = None
    
    def __post_init__(self):
        """Validate and initialize after creation."""
        if isinstance(self.event_type, str):
            self.event_type = EventType(self.event_type)
        if isinstance(self.result, str):
            self.result = EventResult(self.result) if self.result else None
        if isinstance(self.source, str):
            self.source = EventSource(self.source)
    
    def to_schema(self) -> SessionEventSchema:
        """Convert to Pydantic schema."""
        return SessionEventSchema(
            event_id=self.event_id,
            timestamp_utc=self.timestamp_utc,
            event_type=self.event_type,
            workstation_id=self.workstation_id,
            workstation_hostname=self.workstation_hostname,
            windows_session_id=self.windows_session_id,
            session_user_upn=self.session_user_upn,
            session_user_domain=self.session_user_domain,
            client_name=self.client_name,
            client_ip=self.client_ip,
            actor_entra_object_id=self.actor_entra_object_id,
            actor_upn=self.actor_upn,
            result=self.result,
            reason=self.reason,
            source=self.source,
            correlation_id=self.correlation_id,
            agent_version=self.agent_version,
        )
    
    @classmethod
    def from_schema(cls, schema: SessionEventSchema) -> "SessionEvent":
        """Create from Pydantic schema."""
        return cls(
            event_id=schema.event_id,
            timestamp_utc=schema.timestamp_utc,
            event_type=schema.event_type,
            workstation_id=schema.workstation_id,
            workstation_hostname=schema.workstation_hostname,
            windows_session_id=schema.windows_session_id,
            session_user_upn=schema.session_user_upn,
            session_user_domain=schema.session_user_domain,
            client_name=schema.client_name,
            client_ip=schema.client_ip,
            actor_entra_object_id=schema.actor_entra_object_id,
            actor_upn=schema.actor_upn,
            result=schema.result,
            reason=schema.reason,
            source=schema.source,
            correlation_id=schema.correlation_id,
            agent_version=schema.agent_version,
        )
    
    def get_display_type(self) -> str:
        """Get human-readable event type."""
        type_names = {
            EventType.LAUNCH_REQUESTED: "Verbindung gestartet",
            EventType.RDP_LOGON: "RDP-Anmeldung",
            EventType.RDP_RECONNECT: "Wiederverbindung",
            EventType.RDP_DISCONNECT: "Verbindung getrennt",
            EventType.RDP_LOGOFF: "Abmeldung",
            EventType.ADMIN_DISCONNECT_REQUESTED: "Admin: Trennung angefordert",
            EventType.ADMIN_DISCONNECT_COMPLETED: "Admin: Trennung erfolgreich",
            EventType.ADMIN_DISCONNECT_FAILED: "Admin: Trennung fehlgeschlagen",
            EventType.ADMIN_LOGOFF_REQUESTED: "Admin: Abmeldung angefordert",
            EventType.ADMIN_LOGOFF_COMPLETED: "Admin: Abmeldung erfolgreich",
            EventType.ADMIN_LOGOFF_FAILED: "Admin: Abmeldung fehlgeschlagen",
            EventType.MANUAL_FLAG_SET: "Flag gesetzt",
            EventType.MANUAL_FLAG_CLEARED: "Flag entfernt",
            EventType.ADMIN_OVERRIDE: "Admin-Override",
        }
        return type_names.get(self.event_type, str(self.event_type))
    
    def get_display_result(self) -> str:
        """Get human-readable result."""
        if self.result is None:
            return "-"
        result_names = {
            EventResult.SUCCESS: "Erfolg",
            EventResult.FAILED: "Fehlgeschlagen",
            EventResult.PENDING: "Ausstehend",
            EventResult.TIMEOUT: "Timeout",
        }
        return result_names.get(self.result, str(self.result))


@dataclass
class SessionLog:
    """A session log entry combining related events."""
    
    session_id: str
    workstation_id: str
    workstation_hostname: str
    windows_session_id: int
    user_upn: str
    
    # Timestamps
    first_event_utc: datetime
    logon_utc: Optional[datetime] = None
    last_connected_utc: Optional[datetime] = None
    last_disconnected_utc: Optional[datetime] = None
    logoff_utc: Optional[datetime] = None
    
    # Events
    events: list[SessionEvent] = field(default_factory=list)
    
    # Calculated durations
    connected_duration_seconds: Optional[int] = None
    total_duration_seconds: Optional[int] = None
    
    def calculate_durations(self) -> None:
        """Calculate session durations."""
        if self.logon_utc and self.logoff_utc:
            self.total_duration_seconds = int((self.logoff_utc - self.logon_utc).total_seconds())
        
        # Calculate connected time (excluding disconnects)
        connected_time = timedelta()
        last_connect = self.logon_utc
        
        for event in sorted(self.events, key=lambda e: e.timestamp_utc):
            if event.event_type == EventType.RDP_LOGON:
                last_connect = event.timestamp_utc
            elif event.event_type == EventType.RDP_DISCONNECT:
                if last_connect:
                    connected_time += (event.timestamp_utc - last_connect)
                    last_connect = None
            elif event.event_type == EventType.RDP_RECONNECT:
                last_connect = event.timestamp_utc
            elif event.event_type == EventType.RDP_LOGOFF:
                if last_connect:
                    connected_time += (event.timestamp_utc - last_connect)
                last_connect = None
        
        self.connected_duration_seconds = int(connected_time.total_seconds())
    
    def get_connected_duration_display(self) -> str:
        """Get human-readable connected duration."""
        if self.connected_duration_seconds is None:
            self.calculate_durations()
        
        if self.connected_duration_seconds is None:
            return "-"
        
        seconds = self.connected_duration_seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or hours == 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "0m"
    
    def get_total_duration_display(self) -> str:
        """Get human-readable total duration."""
        if self.total_duration_seconds is None:
            self.calculate_durations()
        
        if self.total_duration_seconds is None:
            return "-"
        
        seconds = self.total_duration_seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        parts = []
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or hours == 0:
            parts.append(f"{minutes}m")
        
        return " ".join(parts) if parts else "0m"


def create_mock_session_events(count: int = 20) -> list[SessionEvent]:
    """Create mock session events for development."""
    events = []
    workstation_ids = [f"WS-{i:03d}" for i in range(1, 6)]
    event_types = [
        EventType.LAUNCH_REQUESTED,
        EventType.RDP_LOGON,
        EventType.RDP_RECONNECT,
        EventType.RDP_DISCONNECT,
        EventType.RDP_LOGOFF,
    ]
    
    base_time = datetime.now() - timedelta(days=7)
    
    for i in range(count):
        workstation_id = workstation_ids[i % len(workstation_ids)]
        event_type = event_types[i % len(event_types)]
        
        event = SessionEvent(
            event_id=f"EVT-{i:05d}",
            timestamp_utc=base_time + timedelta(hours=i),
            event_type=event_type,
            workstation_id=workstation_id,
            workstation_hostname=f"ws{i % 5 + 1:03d}.kirschke.local",
            windows_session_id=1 if i % 3 != 0 else 2,
            session_user_upn=generate_test_upn(),
            session_user_domain="prof-kirschke.de",
            client_name=f"CLIENT-{i % 3 + 1}",
            client_ip=f"192.168.1.{i % 25 + 1}",
            actor_entra_object_id=generate_test_entra_id(),
            actor_upn=generate_test_upn(),
            result=EventResult.SUCCESS,
            source=EventSource.PORTAL if i % 2 == 0 else EventSource.AGENT,
        )
        events.append(event)
    
    return events


def create_mock_session_logs(count: int = 5) -> list[SessionLog]:
    """Create mock session logs for development."""
    logs = []
    
    for i in range(count):
        workstation_id = f"WS-{i + 1:03d}"
        base_time = datetime.now() - timedelta(days=count - i)
        
        # Create events for this session
        events = [
            SessionEvent(
                event_id=f"EVT-{i:05d}-01",
                timestamp_utc=base_time,
                event_type=EventType.LAUNCH_REQUESTED,
                workstation_id=workstation_id,
                workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
                windows_session_id=1,
                session_user_upn=f"user{i + 1}@prof-kirschke.de",
                actor_upn=f"user{i + 1}@prof-kirschke.de",
                source=EventSource.PORTAL,
            ),
            SessionEvent(
                event_id=f"EVT-{i:05d}-02",
                timestamp_utc=base_time + timedelta(minutes=1),
                event_type=EventType.RDP_LOGON,
                workstation_id=workstation_id,
                workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
                windows_session_id=1,
                session_user_upn=f"user{i + 1}@prof-kirschke.de",
                source=EventSource.AGENT,
            ),
            SessionEvent(
                event_id=f"EVT-{i:05d}-03",
                timestamp_utc=base_time + timedelta(hours=2),
                event_type=EventType.RDP_DISCONNECT,
                workstation_id=workstation_id,
                workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
                windows_session_id=1,
                session_user_upn=f"user{i + 1}@prof-kirschke.de",
                source=EventSource.AGENT,
            ),
            SessionEvent(
                event_id=f"EVT-{i:05d}-04",
                timestamp_utc=base_time + timedelta(hours=2, minutes=30),
                event_type=EventType.RDP_RECONNECT,
                workstation_id=workstation_id,
                workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
                windows_session_id=1,
                session_user_upn=f"user{i + 1}@prof-kirschke.de",
                source=EventSource.AGENT,
            ),
            SessionEvent(
                event_id=f"EVT-{i:05d}-05",
                timestamp_utc=base_time + timedelta(hours=4),
                event_type=EventType.RDP_LOGOFF,
                workstation_id=workstation_id,
                workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
                windows_session_id=1,
                session_user_upn=f"user{i + 1}@prof-kirschke.de",
                source=EventSource.AGENT,
            ),
        ]
        
        log = SessionLog(
            session_id=f"SESSION-{i:05d}",
            workstation_id=workstation_id,
            workstation_hostname=f"ws{i + 1:03d}.kirschke.local",
            windows_session_id=1,
            user_upn=f"user{i + 1}@prof-kirschke.de",
            first_event_utc=base_time,
            logon_utc=base_time + timedelta(minutes=1),
            logoff_utc=base_time + timedelta(hours=4),
            events=events,
        )
        log.calculate_durations()
        logs.append(log)
    
    return logs


__all__ = [
    "SessionEvent",
    "SessionLog",
    "create_mock_session_events",
    "create_mock_session_logs",
]
