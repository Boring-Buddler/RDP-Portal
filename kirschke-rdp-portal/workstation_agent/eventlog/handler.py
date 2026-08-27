"""Session event logging and handling for Kirschke RDP Workstation Portal Agent.

This module provides functionality to:
- Detect and log RDP session events
- Queue events for transmission to the portal
- Track session state history
- Generate event IDs and timestamps
"""

from __future__ import annotations

import os
import json
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from pathlib import Path
from threading import Lock
from collections import deque

from shared.enums import EventType, EventResult, EventSource
from shared.schemas import SessionEventSchema
from workstation_agent.wts.monitor import WTSSessionInfo, WTS_CONNECTSTATE_CLASS, WTSMonitor

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class EventLogConfig:
    """Configuration for event logging."""
    
    # Maximum number of events to keep in memory
    max_events_in_memory: int = 1000
    
    # Maximum age of events in memory (in seconds)
    max_event_age_seconds: int = 86400  # 24 hours
    
    # Event log directory
    log_directory: str = os.getenv("AGENT_LOG_DIR", "")
    
    # Whether to persist events to disk
    persist_events: bool = os.getenv("AGENT_PERSIST_EVENTS", "false").lower() == "true"
    
    # Workstation ID (set by agent)
    workstation_id: str = ""
    
    # Workstation hostname
    workstation_hostname: str = ""
    
    # Agent version
    agent_version: str = os.getenv("AGENT_VERSION", "1.0.0")
    
    @classmethod
    def from_env(cls) -> "EventLogConfig":
        """Create configuration from environment variables."""
        import socket
        
        hostname = socket.gethostname()
        workstation_id = os.getenv("WORKSTATION_ID", hostname)
        
        # Set default log directory
        log_dir = os.getenv("AGENT_LOG_DIR", "")
        if not log_dir:
            log_dir = str(Path.home() / ".kirschke" / "rdp-agent" / "logs")
        
        return cls(
            log_directory=log_dir,
            workstation_id=workstation_id,
            workstation_hostname=hostname,
        )


# =============================================================================
# Session Event
# =============================================================================

@dataclass
class AgentSessionEvent:
    """Internal representation of a session event for the agent."""
    
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    event_type: EventType = EventType.LAUNCH_REQUESTED
    timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    workstation_id: str = ""
    workstation_hostname: str = ""
    windows_session_id: Optional[int] = None
    session_user_upn: Optional[str] = None
    session_user_domain: Optional[str] = None
    client_name: Optional[str] = None
    client_ip: Optional[str] = None
    actor_entra_object_id: Optional[str] = None
    actor_upn: Optional[str] = None
    result: Optional[EventResult] = None
    reason: Optional[str] = None
    source: EventSource = EventSource.AGENT
    correlation_id: Optional[str] = None
    agent_version: str = ""
    
    # Additional metadata
    raw_data: dict = field(default_factory=dict)
    processed: bool = False
    sent_to_portal: bool = False
    
    def to_schema(self) -> SessionEventSchema:
        """Convert to SessionEventSchema for transmission."""
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
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp_utc": self.timestamp_utc.isoformat(),
            "workstation_id": self.workstation_id,
            "workstation_hostname": self.workstation_hostname,
            "windows_session_id": self.windows_session_id,
            "session_user_upn": self.session_user_upn,
            "session_user_domain": self.session_user_domain,
            "client_name": self.client_name,
            "client_ip": self.client_ip,
            "actor_entra_object_id": self.actor_entra_object_id,
            "actor_upn": self.actor_upn,
            "result": self.result.value if self.result else None,
            "reason": self.reason,
            "source": self.source.value,
            "correlation_id": self.correlation_id,
            "agent_version": self.agent_version,
            "processed": self.processed,
            "sent_to_portal": self.sent_to_portal,
        }


# =============================================================================
# Event Queue
# =============================================================================

class EventQueue:
    """Queue for storing session events before transmission.
    
    This class provides thread-safe storage for events that need to be
    sent to the portal. Events are stored in memory and optionally
    persisted to disk.
    """
    
    def __init__(self, config: Optional[EventLogConfig] = None):
        """Initialize the event queue.
        
        Args:
            config: Optional event log configuration
        """
        self.config = config or EventLogConfig.from_env()
        self._events: deque[AgentSessionEvent] = deque()
        self._lock = Lock()
        self._event_history: dict[str, AgentSessionEvent] = {}
        
        # Ensure log directory exists
        if self.config.persist_events and self.config.log_directory:
            Path(self.config.log_directory).mkdir(parents=True, exist_ok=True)
        
        # Load persisted events if enabled
        if self.config.persist_events:
            self._load_persisted_events()
    
    def _load_persisted_events(self) -> None:
        """Load events from disk."""
        if not self.config.log_directory:
            return
        
        try:
            event_file = Path(self.config.log_directory) / "pending_events.json"
            if event_file.exists():
                with open(event_file, "r", encoding="utf-8") as f:
                    events_data = json.load(f)
                    for event_data in events_data:
                        event = AgentSessionEvent(**event_data)
                        self._events.append(event)
                        self._event_history[event.event_id] = event
        except Exception as e:
            logger.warning(f"Failed to load persisted events: {e}")
    
    def _save_persisted_events(self) -> None:
        """Save events to disk."""
        if not self.config.persist_events or not self.config.log_directory:
            return
        
        try:
            event_file = Path(self.config.log_directory) / "pending_events.json"
            events_data = [e.to_dict() for e in self._events]
            with open(event_file, "w", encoding="utf-8") as f:
                json.dump(events_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save persisted events: {e}")
    
    def add_event(self, event: AgentSessionEvent) -> None:
        """Add an event to the queue.
        
        Args:
            event: Event to add
        """
        with self._lock:
            # Update event with config values
            if not event.workstation_id and self.config.workstation_id:
                event.workstation_id = self.config.workstation_id
            if not event.workstation_hostname and self.config.workstation_hostname:
                event.workstation_hostname = self.config.workstation_hostname
            if not event.agent_version and self.config.agent_version:
                event.agent_version = self.config.agent_version
            
            # Add to queue
            self._events.append(event)
            self._event_history[event.event_id] = event
            
            # Trim queue if too large
            while len(self._events) > self.config.max_events_in_memory:
                old_event = self._events.popleft()
                self._event_history.pop(old_event.event_id, None)
            
            # Persist if enabled
            if self.config.persist_events:
                self._save_persisted_events()
        
        logger.debug(f"Event added: {event.event_id} ({event.event_type.value})")
    
    def get_events(self, limit: Optional[int] = None) -> list[AgentSessionEvent]:
        """Get events from the queue.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of events
        """
        with self._lock:
            if limit:
                return list(self._events)[:limit]
            return list(self._events)
    
    def get_unsent_events(self) -> list[AgentSessionEvent]:
        """Get events that haven't been sent to the portal yet.
        
        Returns:
            List of unsent events
        """
        with self._lock:
            return [e for e in self._events if not e.sent_to_portal]
    
    def mark_event_sent(self, event_id: str) -> bool:
        """Mark an event as sent to the portal.
        
        Args:
            event_id: ID of the event to mark as sent
            
        Returns:
            True if event was found and marked
        """
        with self._lock:
            if event_id in self._event_history:
                self._event_history[event_id].sent_to_portal = True
                self._save_persisted_events()
                return True
            return False
    
    def mark_all_sent(self) -> int:
        """Mark all events as sent.
        
        Returns:
            Number of events marked as sent
        """
        with self._lock:
            count = 0
            for event in self._events:
                if not event.sent_to_portal:
                    event.sent_to_portal = True
                    count += 1
            
            if self.config.persist_events:
                self._save_persisted_events()
            
            return count
    
    def remove_event(self, event_id: str) -> bool:
        """Remove an event from the queue.
        
        Args:
            event_id: ID of the event to remove
            
        Returns:
            True if event was found and removed
        """
        with self._lock:
            # Remove from queue
            for i, event in enumerate(self._events):
                if event.event_id == event_id:
                    del self._events[i]
                    break
            
            # Remove from history
            if event_id in self._event_history:
                del self._event_history[event_id]
                self._save_persisted_events()
                return True
            return False
    
    def clear(self) -> None:
        """Clear all events from the queue."""
        with self._lock:
            self._events.clear()
            self._event_history.clear()
            
            if self.config.persist_events:
                self._save_persisted_events()
    
    def get_event_by_id(self, event_id: str) -> Optional[AgentSessionEvent]:
        """Get an event by its ID.
        
        Args:
            event_id: Event ID to find
            
        Returns:
            Event if found, None otherwise
        """
        with self._lock:
            return self._event_history.get(event_id)
    
    def count(self) -> int:
        """Get the number of events in the queue.
        
        Returns:
            Number of events
        """
        with self._lock:
            return len(self._events)
    
    def cleanup_old_events(self) -> int:
        """Remove events older than max_event_age_seconds.
        
        Returns:
            Number of events removed
        """
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(
                seconds=self.config.max_event_age_seconds
            )
            
            removed = 0
            while self._events and self._events[0].timestamp_utc < cutoff:
                old_event = self._events.popleft()
                self._event_history.pop(old_event.event_id, None)
                removed += 1
            
            if removed > 0 and self.config.persist_events:
                self._save_persisted_events()
            
            return removed


# Import timedelta at the method level to avoid circular imports
from datetime import timedelta


# =============================================================================
# Session Event Detector
# =============================================================================

class SessionEventDetector:
    """Detect and create session events from WTS session changes.
    
    This class monitors WTS session state changes and creates
    appropriate SessionEventSchema objects for transmission to the portal.
    """
    
    def __init__(
        self,
        config: Optional[EventLogConfig] = None,
        event_queue: Optional[EventQueue] = None,
        wts_monitor: Optional[WTSMonitor] = None,
    ):
        """Initialize the session event detector.
        
        Args:
            config: Optional event log configuration
            event_queue: Optional event queue for storing events
            wts_monitor: Optional WTS monitor instance
        """
        self.config = config or EventLogConfig.from_env()
        self.event_queue = event_queue or EventQueue(self.config)
        self.wts_monitor = wts_monitor or WTSMonitor()
        
        # Track last known session states
        self._last_session_states: dict[int, WTSSessionInfo] = {}
        
        # Track correlation IDs for multi-part events
        self._correlation_id: Optional[str] = None
    
    def detect_session_changes(self) -> list[AgentSessionEvent]:
        """Detect session changes and create events.
        
        Returns:
            List of created events
        """
        events: list[AgentSessionEvent] = []
        
        try:
            current_sessions = self.wts_monitor.get_all_sessions()
            
            # Build dictionary of current sessions
            current_session_dict = {s.session_id: s for s in current_sessions}
            
            # Check for new sessions
            for session_id, session in current_session_dict.items():
                if session_id not in self._last_session_states:
                    # New session detected
                    event = self._create_session_start_event(session)
                    if event:
                        events.append(event)
                else:
                    # Check for state changes
                    old_session = self._last_session_states[session_id]
                    if old_session.connect_state != session.connect_state:
                        event = self._create_session_state_change_event(
                            old_session, session
                        )
                        if event:
                            events.append(event)
            
            # Check for ended sessions
            for session_id in list(self._last_session_states.keys()):
                if session_id not in current_session_dict:
                    old_session = self._last_session_states[session_id]
                    event = self._create_session_end_event(old_session)
                    if event:
                        events.append(event)
            
            # Update last known states
            self._last_session_states = current_session_dict.copy()
            
        except Exception as e:
            logger.error(f"Failed to detect session changes: {e}")
        
        return events
    
    def _create_session_start_event(self, session: WTSSessionInfo) -> Optional[AgentSessionEvent]:
        """Create an event for a new session.
        
        Args:
            session: Session information
            
        Returns:
            AgentSessionEvent if event should be created
        """
        if session.is_console_session:
            # Skip console sessions
            return None
        
        # Determine event type based on connect state
        if session.connect_state == WTS_CONNECTSTATE_CLASS.WTSConnectQuery:
            event_type = EventType.RDP_LOGON
        elif session.connect_state in [
            WTS_CONNECTSTATE_CLASS.WTSActive,
            WTS_CONNECTSTATE_CLASS.WTSConnected,
        ]:
            event_type = EventType.RDP_LOGON
        else:
            return None
        
        event = AgentSessionEvent(
            event_type=event_type,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            windows_session_id=session.session_id,
            session_user_upn=self._format_upn(session.username, session.domain),
            session_user_domain=session.domain,
            client_name=session.client_name,
            client_ip=session.client_address,
            result=EventResult.SUCCESS,
            reason=f"Session started - {session.connect_state.name if session.connect_state else 'unknown'}",
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
            correlation_id=self._correlation_id or str(uuid.uuid4())[:8],
        )
        
        self.event_queue.add_event(event)
        return event
    
    def _create_session_state_change_event(
        self, old_session: WTSSessionInfo, new_session: WTSSessionInfo
    ) -> Optional[AgentSessionEvent]:
        """Create an event for a session state change.
        
        Args:
            old_session: Previous session state
            new_session: New session state
            
        Returns:
            AgentSessionEvent if event should be created
        """
        if old_session.connect_state == new_session.connect_state:
            return None
        
        # Map state transitions to event types
        transition_mapping = {
            (WTS_CONNECTSTATE_CLASS.WTSConnectQuery, WTS_CONNECTSTATE_CLASS.WTSActive): EventType.RDP_LOGON,
            (WTS_CONNECTSTATE_CLASS.WTSConnectQuery, WTS_CONNECTSTATE_CLASS.WTSConnected): EventType.RDP_LOGON,
            (WTS_CONNECTSTATE_CLASS.WTSActive, WTS_CONNECTSTATE_CLASS.WTSDisconnected): EventType.RDP_DISCONNECT,
            (WTS_CONNECTSTATE_CLASS.WTSConnected, WTS_CONNECTSTATE_CLASS.WTSDisconnected): EventType.RDP_DISCONNECT,
            (WTS_CONNECTSTATE_CLASS.WTSDisconnected, WTS_CONNECTSTATE_CLASS.WTSActive): EventType.RDP_RECONNECT,
            (WTS_CONNECTSTATE_CLASS.WTSDisconnected, WTS_CONNECTSTATE_CLASS.WTSConnected): EventType.RDP_RECONNECT,
            (WTS_CONNECTSTATE_CLASS.WTSActive, WTS_CONNECTSTATE_CLASS.WTSIdle): EventType.RDP_DISCONNECT,
        }
        
        transition = (old_session.connect_state, new_session.connect_state)
        event_type = transition_mapping.get(transition)
        
        if not event_type:
            # Generic state change
            event_type = EventType.LAUNCH_REQUESTED  # Will be overridden
        
        # For disconnect/reconnect, use specific event types
        if new_session.connect_state == WTS_CONNECTSTATE_CLASS.WTSDisconnected:
            event_type = EventType.RDP_DISCONNECT
        elif old_session.connect_state == WTS_CONNECTSTATE_CLASS.WTSDisconnected:
            event_type = EventType.RDP_RECONNECT
        
        event = AgentSessionEvent(
            event_type=event_type,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            windows_session_id=new_session.session_id,
            session_user_upn=self._format_upn(new_session.username, new_session.domain),
            session_user_domain=new_session.domain,
            client_name=new_session.client_name,
            client_ip=new_session.client_address,
            result=EventResult.SUCCESS,
            reason=f"State changed from {old_session.connect_state.name} to {new_session.connect_state.name}",
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
            correlation_id=self._correlation_id or str(uuid.uuid4())[:8],
        )
        
        self.event_queue.add_event(event)
        return event
    
    def _create_session_end_event(self, session: WTSSessionInfo) -> Optional[AgentSessionEvent]:
        """Create an event for an ended session.
        
        Args:
            session: Session that ended
            
        Returns:
            AgentSessionEvent if event should be created
        """
        if session.is_console_session:
            return None
        
        event = AgentSessionEvent(
            event_type=EventType.RDP_LOGOFF,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            windows_session_id=session.session_id,
            session_user_upn=self._format_upn(session.username, session.domain),
            session_user_domain=session.domain,
            client_name=session.client_name,
            client_ip=session.client_address,
            result=EventResult.SUCCESS,
            reason=f"Session ended - was {session.connect_state.name if session.connect_state else 'unknown'}",
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
            correlation_id=self._correlation_id or str(uuid.uuid4())[:8],
        )
        
        self.event_queue.add_event(event)
        return event
    
    def _format_upn(self, username: Optional[str], domain: Optional[str]) -> Optional[str]:
        """Format username and domain as UPN.
        
        Args:
            username: Username
            domain: Domain
            
        Returns:
            Formatted UPN (user@domain) or None
        """
        if not username:
            return None
        
        if domain and domain != "":
            # Try to format as UPN
            return f"{username}@{domain}"
        
        return username
    
    def get_current_session_event(self) -> Optional[AgentSessionEvent]:
        """Get an event for the current session (for manual flag setting).
        
        Returns:
            AgentSessionEvent for current session
        """
        current_session = self.wts_monitor.get_current_session()
        if not current_session:
            return None
        
        event = AgentSessionEvent(
            event_type=EventType.MANUAL_FLAG_SET,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            windows_session_id=current_session.session_id,
            session_user_upn=self._format_upn(current_session.username, current_session.domain),
            session_user_domain=current_session.domain,
            client_name=current_session.client_name,
            result=EventResult.SUCCESS,
            reason="Manual flag set by current user",
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
        )
        
        return event
    
    def log_manual_flag_event(
        self,
        flag_type: str,
        set_by_upn: Optional[str],
        set_by_object_id: Optional[str],
        reason: Optional[str] = None,
        project: Optional[str] = None,
    ) -> Optional[AgentSessionEvent]:
        """Log a manual flag event.
        
        Args:
            flag_type: Type of flag being set
            set_by_upn: UPN of user setting the flag
            set_by_object_id: Object ID of user setting the flag
            reason: Reason for setting the flag
            project: Project reference
            
        Returns:
            AgentSessionEvent that was created
        """
        event = AgentSessionEvent(
            event_type=EventType.MANUAL_FLAG_SET,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            actor_upn=set_by_upn,
            actor_entra_object_id=set_by_object_id,
            result=EventResult.SUCCESS,
            reason=f"Flag set: {flag_type}" + (f" - {reason}" if reason else ""),
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
        )
        
        self.event_queue.add_event(event)
        return event
    
    def log_admin_command_event(
        self,
        command_type: str,
        requested_by_upn: str,
        requested_by_object_id: str,
        result: EventResult,
        result_message: Optional[str] = None,
    ) -> Optional[AgentSessionEvent]:
        """Log an admin command execution event.
        
        Args:
            command_type: Type of command executed
            requested_by_upn: UPN of requester
            requested_by_object_id: Object ID of requester
            result: Result of the command
            result_message: Additional result message
            
        Returns:
            AgentSessionEvent that was created
        """
        event_type_mapping = {
            "disconnect_session": EventType.ADMIN_DISCONNECT_REQUESTED,
            "logoff_session": EventType.ADMIN_LOGOFF_REQUESTED,
            "clear_manual_flag": EventType.MANUAL_FLAG_CLEARED,
            "refresh_status": EventType.LAUNCH_REQUESTED,
        }
        
        event_type = event_type_mapping.get(command_type, EventType.ADMIN_OVERRIDE)
        
        # For successful commands, use COMPLETED variant
        if result == EventResult.SUCCESS and command_type in ["disconnect_session", "logoff_session"]:
            if command_type == "disconnect_session":
                event_type = EventType.ADMIN_DISCONNECT_COMPLETED
            elif command_type == "logoff_session":
                event_type = EventType.ADMIN_LOGOFF_COMPLETED
        
        # For failed commands, use FAILED variant
        if result == EventResult.FAILED and command_type in ["disconnect_session", "logoff_session"]:
            if command_type == "disconnect_session":
                event_type = EventType.ADMIN_DISCONNECT_FAILED
            elif command_type == "logoff_session":
                event_type = EventType.ADMIN_LOGOFF_FAILED
        
        event = AgentSessionEvent(
            event_type=event_type,
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.workstation_hostname,
            actor_upn=requested_by_upn,
            actor_entra_object_id=requested_by_object_id,
            result=result,
            reason=result_message or f"Command {command_type} executed",
            source=EventSource.AGENT,
            agent_version=self.config.agent_version,
        )
        
        self.event_queue.add_event(event)
        return event


# =============================================================================
# Factory and Exports
# =============================================================================

def create_event_queue(config: Optional[EventLogConfig] = None) -> EventQueue:
    """Create an EventQueue instance.
    
    Args:
        config: Optional event log configuration
        
    Returns:
        EventQueue instance
    """
    return EventQueue(config)


def create_session_event_detector(
    config: Optional[EventLogConfig] = None,
    event_queue: Optional[EventQueue] = None,
    wts_monitor: Optional[WTSMonitor] = None,
) -> SessionEventDetector:
    """Create a SessionEventDetector instance.
    
    Args:
        config: Optional event log configuration
        event_queue: Optional event queue
        wts_monitor: Optional WTS monitor
        
    Returns:
        SessionEventDetector instance
    """
    return SessionEventDetector(config, event_queue, wts_monitor)


__all__ = [
    "EventLogConfig",
    "AgentSessionEvent",
    "EventQueue",
    "SessionEventDetector",
    "create_event_queue",
    "create_session_event_detector",
]
