"""Windows Service for Kirschke RDP Workstation Agent.

This module provides the main service that runs on each managed workstation
to monitor RDP sessions and execute admin commands.

Features:
- Runs as a Windows service
- Monitors RDP sessions using WTS API
- Detects session state changes (logon, logoff, disconnect, reconnect)
- Submits session events to SharePoint via Graph API
- Polls for admin commands and executes them
- Updates workstation status in SharePoint
- Handles manual flags
"""

import os
import sys
import time
import json
import logging
import socket
import win32serviceutil
import win32service
import win32event
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from shared.enums import (
    AgentStatus,
    SessionState,
    ManualFlagType,
    CommandType,
    CommandStatus,
)
from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class AgentConfig:
    """Configuration for the workstation agent."""
    
    # Workstation identification
    workstation_id: str = os.getenv("WORKSTATION_ID", "")
    hostname: str = socket.gethostname()
    
    # Agent settings
    agent_version: str = os.getenv("AGENT_VERSION", "1.0.0")
    poll_interval: int = int(os.getenv("AGENT_POLL_INTERVAL", "30"))  # seconds
    
    # Microsoft Entra ID settings
    tenant_id: str = os.getenv("TENANT_ID", "")
    client_id: str = os.getenv("AGENT_CLIENT_ID", "")
    authority: str = os.getenv("AUTHORITY", "")
    certificate_thumbprint: str = os.getenv("AGENT_CERT_THUMBPRINT", "")
    certificate_store: str = os.getenv("AGENT_CERT_STORE", "My")
    
    # SharePoint settings
    sharepoint_site_id: str = os.getenv("SHAREPOINT_SITE_ID", "")
    workstations_list: str = os.getenv("SHAREPOINT_WORKSTATIONS_LIST", "RDP_Workstations")
    sessions_list: str = os.getenv("SHAREPOINT_SESSIONS_LIST", "RDP_SessionEvents")
    commands_list: str = os.getenv("SHAREPOINT_COMMANDS_LIST", "RDP_AdminCommands")
    access_rules_list: str = os.getenv("SHAREPOINT_ACCESS_RULES_LIST", "RDP_AccessRules")
    
    # Logging settings
    log_level: str = os.getenv("AGENT_LOG_LEVEL", "INFO")
    log_file: str = os.getenv("AGENT_LOG_FILE", "")
    publish_local_status: bool = os.getenv("AGENT_PUBLISH_LOCAL_STATUS", "true").lower() == "true"
    
    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Create configuration from environment variables."""
        # Build authority if not set
        authority = os.getenv("AUTHORITY", "")
        if not authority and os.getenv("TENANT_ID"):
            authority = f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}"
        
        # Set workstation ID from hostname if not set
        workstation_id = os.getenv("WORKSTATION_ID", "")
        if not workstation_id:
            workstation_id = socket.gethostname()
        
        # Set default log file
        log_file = os.getenv("AGENT_LOG_FILE", "")
        if not log_file:
            log_dir = Path.home() / ".kirschke" / "rdp-agent" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = str(log_dir / "agent.log")
        
        return cls(
            workstation_id=workstation_id,
            hostname=socket.gethostname(),
            authority=authority,
            log_file=log_file,
        )
    
    def validate(self) -> bool:
        """Validate required configuration."""
        # For Phase 1, we can run with minimal config
        # For production, we need tenant_id, client_id, certificate_thumbprint
        return bool(self.workstation_id and self.hostname)

    def has_graph_configuration(self) -> bool:
        """Return whether the external status channel can be used."""
        return all(
            (
                self.tenant_id,
                self.client_id,
                self.certificate_thumbprint,
                self.sharepoint_site_id,
            )
        )


# =============================================================================
# Agent State
# =============================================================================

@dataclass
class AgentState:
    """Current state of the agent."""
    
    # Agent status
    status: AgentStatus = AgentStatus.OFFLINE
    
    # Last activity timestamps
    last_poll_time: Optional[datetime] = None
    last_event_time: Optional[datetime] = None
    last_command_check_time: Optional[datetime] = None
    last_status_update_time: Optional[datetime] = None
    
    # Workstation information
    workstation_id: str = ""
    workstation_hostname: str = ""
    
    # Current session information
    current_session_state: SessionState = SessionState.NONE
    current_session_user: Optional[str] = None
    current_windows_session_id: Optional[int] = None
    
    # Manual flag
    manual_flag_type: ManualFlagType = ManualFlagType.NONE
    
    # Counters
    events_submitted: int = 0
    commands_executed: int = 0
    errors: int = 0
    
    def update_session_info(
        self,
        session_state: SessionState,
        session_user: Optional[str] = None,
        windows_session_id: Optional[int] = None,
    ) -> None:
        """Update current session information."""
        changed = (
            self.current_session_state != session_state
            or self.current_session_user != session_user
            or self.current_windows_session_id != windows_session_id
        )
        self.current_session_state = session_state
        self.current_session_user = session_user
        self.current_windows_session_id = windows_session_id
        if changed:
            self.last_event_time = datetime.now(timezone.utc)
    
    def increment_events_submitted(self) -> None:
        """Increment the events submitted counter."""
        self.events_submitted += 1
    
    def increment_commands_executed(self) -> None:
        """Increment the commands executed counter."""
        self.commands_executed += 1
    
    def increment_errors(self) -> None:
        """Increment the error counter."""
        self.errors += 1


# =============================================================================
# Command Handler
# =============================================================================

class CommandHandler:
    """Handle execution of admin commands."""
    
    def __init__(self):
        """Initialize the command handler."""
        pass
    
    def execute_command(self, command: dict) -> tuple[bool, str]:
        """Execute an admin command.
        
        Args:
            command: Command dictionary with type and parameters
            
        Returns:
            Tuple of (success, message)
        """
        command_type = command.get("command_type", "")
        
        try:
            if command_type == CommandType.REFRESH_STATUS.value:
                return self._execute_refresh_status(command)
            elif command_type == CommandType.DISCONNECT_SESSION.value:
                return self._execute_disconnect_session(command)
            elif command_type == CommandType.LOGOFF_SESSION.value:
                return self._execute_logoff_session(command)
            elif command_type == CommandType.CLEAR_MANUAL_FLAG.value:
                return self._execute_clear_manual_flag(command)
            else:
                return False, f"Unknown command type: {command_type}"
        except Exception as e:
            return False, f"Command execution failed: {str(e)}"
    
    def _execute_refresh_status(self, command: dict) -> tuple[bool, str]:
        """Execute refresh status command.
        
        Args:
            command: Command dictionary
            
        Returns:
            Tuple of (success, message)
        """
        # This command just forces the agent to update its status
        return True, "Status refreshed"
    
    def _execute_disconnect_session(self, command: dict) -> tuple[bool, str]:
        """Execute disconnect session command.
        
        Args:
            command: Command dictionary
            
        Returns:
            Tuple of (success, message)
        """
        target_session_id = command.get("target_windows_session_id")
        
        if target_session_id is None:
            return False, "Target session ID not specified"
        
        try:
            import ctypes
            
            # Use WTS API to disconnect session
            wtsapi32 = ctypes.windll.Wtsapi32
            
            # WTSDisconnectSession function
            wtsapi32.WTSDisconnectSession.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_bool,
            ]
            wtsapi32.WTSDisconnectSession.restype = ctypes.c_bool
            
            # Disconnect the session
            result = wtsapi32.WTSDisconnectSession(
                None,  # Local machine
                target_session_id,
                False,  # Don't wait for disconnect
            )
            
            if result:
                return True, f"Session {target_session_id} disconnected"
            else:
                return False, f"Failed to disconnect session {target_session_id}"
                
        except Exception as e:
            return False, f"Failed to disconnect session: {str(e)}"
    
    def _execute_logoff_session(self, command: dict) -> tuple[bool, str]:
        """Execute logoff session command.
        
        Args:
            command: Command dictionary
            
        Returns:
            Tuple of (success, message)
        """
        target_session_id = command.get("target_windows_session_id")
        
        if target_session_id is None:
            return False, "Target session ID not specified"
        
        try:
            import ctypes
            
            # Use WTS API to log off session
            wtsapi32 = ctypes.windll.Wtsapi32
            
            # WTSLogoffSession function
            wtsapi32.WTSLogoffSession.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_bool,
            ]
            wtsapi32.WTSLogoffSession.restype = ctypes.c_bool
            
            # Log off the session
            result = wtsapi32.WTSLogoffSession(
                None,  # Local machine
                target_session_id,
                False,  # Don't wait for logoff
            )
            
            if result:
                return True, f"Session {target_session_id} logged off"
            else:
                return False, f"Failed to log off session {target_session_id}"
                
        except Exception as e:
            return False, f"Failed to log off session: {str(e)}"
    
    def _execute_clear_manual_flag(self, command: dict) -> tuple[bool, str]:
        """Execute clear manual flag command.
        
        Args:
            command: Command dictionary
            
        Returns:
            Tuple of (success, message)
        """
        # This command clears the manual flag on the workstation
        # The actual flag clearing happens in SharePoint, so we just acknowledge
        return True, "Manual flag cleared"


# =============================================================================
# Workstation Agent
# =============================================================================

class WorkstationAgent:
    """Main workstation agent class.
    
    This class orchestrates all agent activities:
    - Monitoring RDP sessions
    - Submitting events to SharePoint
    - Executing admin commands
    - Updating workstation status
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize the workstation agent.
        
        Args:
            config: Optional agent configuration
        """
        self.config = config or AgentConfig.from_env()
        self.state = AgentState(
            workstation_id=self.config.workstation_id,
            workstation_hostname=self.config.hostname,
        )
        
        # Initialize components
        self._initialize_logging()
        self.command_handler = CommandHandler()
        
        # Lazy-loaded components
        self._wts_monitor = None
        self._event_detector = None
        self._event_queue = None
        self._graph_client = None
        self._last_rdp_sessions = []
        
        # Service control
        self._running = False
        
        logger.info(f"Workstation agent initialized: {self.config.workstation_id}")
    
    def _initialize_logging(self) -> None:
        """Initialize logging configuration."""
        log_level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        
        # Configure root logger
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
            ],
        )
        
        # Add file handler if configured
        if self.config.log_file:
            log_dir = Path(self.config.log_file).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            
            file_handler = logging.FileHandler(
                self.config.log_file,
                encoding="utf-8",
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            ))
            
            logging.getLogger().addHandler(file_handler)
        
        logger.info(f"Logging configured: level={log_level}, file={self.config.log_file}")
    
    def _get_wts_monitor(self):
        """Get or create WTS monitor."""
        if self._wts_monitor is None:
            from workstation_agent.wts.monitor import WTSMonitor
            self._wts_monitor = WTSMonitor()
        return self._wts_monitor
    
    def _get_event_detector(self):
        """Get or create event detector."""
        if self._event_detector is None:
            from workstation_agent.eventlog.handler import (
                SessionEventDetector,
                EventLogConfig,
            )
            event_config = EventLogConfig(
                workstation_id=self.config.workstation_id,
                workstation_hostname=self.config.hostname,
                agent_version=self.config.agent_version,
            )
            self._event_detector = SessionEventDetector(event_config)
        return self._event_detector
    
    def _get_event_queue(self):
        """Get or create event queue."""
        if self._event_queue is None:
            from workstation_agent.eventlog.handler import (
                EventQueue,
                EventLogConfig,
            )
            event_config = EventLogConfig(
                workstation_id=self.config.workstation_id,
                workstation_hostname=self.config.hostname,
                agent_version=self.config.agent_version,
            )
            self._event_queue = EventQueue(event_config)
        return self._event_queue
    
    def _get_graph_client(self):
        """Get or create Graph client."""
        if self._graph_client is None:
            from workstation_agent.graph.client import (
                AgentGraphConfig,
                AgentGraphClient,
            )
            graph_config = AgentGraphConfig(
                tenant_id=self.config.tenant_id,
                client_id=self.config.client_id,
                authority=self.config.authority,
                certificate_thumbprint=self.config.certificate_thumbprint,
                certificate_store=self.config.certificate_store,
                sharepoint_site_id=self.config.sharepoint_site_id,
                workstations_list=self.config.workstations_list,
                sessions_list=self.config.sessions_list,
                commands_list=self.config.commands_list,
                access_rules_list=self.config.access_rules_list,
            )
            self._graph_client = AgentGraphClient(graph_config)
        return self._graph_client
    
    def start(self) -> bool:
        """Start the agent.
        
        Returns:
            True if agent started successfully
        """
        if not self.config.validate():
            logger.error("Agent configuration is invalid")
            return False
        
        self._running = True
        self.state.status = AgentStatus.ONLINE
        self.state.last_poll_time = datetime.now(timezone.utc)
        
        logger.info(f"Workstation agent started: {self.config.workstation_id}")

        self._refresh_session_state()
        self._publish_local_snapshot()
        
        # Run initial sync
        if self.config.has_graph_configuration():
            self._sync_with_portal()
        else:
            logger.info("Graph synchronization disabled: no complete external configuration")
        
        return True
    
    def stop(self) -> None:
        """Stop the agent."""
        self._running = False
        self.state.status = AgentStatus.OFFLINE
        self._publish_local_snapshot()

        if self._wts_monitor is not None:
            self._wts_monitor.close()
            self._wts_monitor = None
        
        logger.info("Workstation agent stopped")
    
    def poll(self) -> None:
        """Perform a polling cycle.
        
        This method should be called periodically to:
        - Detect session changes
        - Submit events
        - Check for admin commands
        - Update status
        """
        if not self._running:
            return
        
        try:
            logger.debug(f"Polling cycle started: {self.config.workstation_id}")
            
            # Update timestamp
            self.state.last_poll_time = datetime.now(timezone.utc)

            # Read the actual Windows RDP session state first.
            self._refresh_session_state()
            
            # 1. Detect session changes and create events
            self._detect_session_changes()
            
            # 2. Submit queued events to portal
            self._submit_events()
            
            # 3. Check for and execute admin commands
            self._check_admin_commands()
            
            # 4. Update workstation status
            self._update_status()
            
            # 5. Cleanup old events
            self._cleanup_old_events()

            # 6. Publish the local test snapshot even without Graph credentials.
            self._publish_local_snapshot()
            
            logger.debug(f"Polling cycle completed: {self.config.workstation_id}")
            
        except Exception as e:
            logger.error(f"Polling cycle failed: {str(e)}")
            self.state.increment_errors()

    def _refresh_session_state(self) -> None:
        """Refresh the primary occupied session from the local WTS API."""
        try:
            monitor = self._get_wts_monitor()
            sessions = monitor.get_rdp_sessions()
            priorities = {
                SessionState.CONNECTED: 4,
                SessionState.RECONNECTED: 4,
                SessionState.LOGON: 3,
                SessionState.DISCONNECTED: 2,
            }
            primary = max(
                sessions,
                key=lambda session: priorities.get(session.session_state, 0),
                default=None,
            )
            self._last_rdp_sessions = sessions
            if self._running:
                self.state.status = AgentStatus.ONLINE
            if primary is None:
                self.state.update_session_info(SessionState.NONE)
                return
            self.state.update_session_info(
                primary.session_state,
                primary.full_username or None,
                primary.session_id,
            )
        except Exception as e:
            logger.error(f"Failed to refresh WTS session state: {str(e)}")
            self.state.status = AgentStatus.ERROR
            self.state.increment_errors()

    def _publish_local_snapshot(self) -> None:
        """Write an atomic local status file for the credential-free test build."""
        if not self.config.publish_local_status:
            return
        try:
            snapshot = AgentSnapshot(
                workstation_id=self.config.workstation_id,
                hostname=self.config.hostname,
                agent_version=self.config.agent_version,
                observed_at_utc=datetime.now(timezone.utc),
                agent_status=self.state.status,
                current_session_state=self.state.current_session_state,
                current_session_user=self.state.current_session_user,
                current_windows_session_id=self.state.current_windows_session_id,
                rdp_sessions=[session.to_dict() for session in self._last_rdp_sessions],
            )
            write_agent_snapshot(snapshot)
        except OSError as e:
            logger.error(f"Failed to publish local agent status: {str(e)}")
            self.state.increment_errors()
    
    def _detect_session_changes(self) -> None:
        """Detect RDP session changes and create events."""
        try:
            detector = self._get_event_detector()
            events = detector.detect_session_changes()
            
            for event in events:
                logger.info(f"Session event detected: {event.event_type.value}")
                self.state.increment_events_submitted()
            
        except Exception as e:
            logger.error(f"Failed to detect session changes: {str(e)}")
    
    def _submit_events(self) -> None:
        """Submit queued events to the portal."""
        if not self.config.has_graph_configuration():
            return
        try:
            queue = self._get_event_queue()
            unsent_events = queue.get_unsent_events()
            
            if not unsent_events:
                return
            
            graph_client = self._get_graph_client()
            
            # Authenticate if needed
            if not graph_client.is_authenticated():
                if not graph_client.authenticate():
                    logger.warning("Graph authentication failed, will retry later")
                    return
            
            # Submit each event
            for event in unsent_events:
                try:
                    schema_event = event.to_schema()
                    if graph_client.create_session_event(schema_event):
                        queue.mark_event_sent(event.event_id)
                        logger.info(f"Event submitted: {event.event_id} ({event.event_type.value})")
                    else:
                        logger.warning(f"Failed to submit event: {event.event_id}")
                except Exception as e:
                    logger.error(f"Failed to submit event {event.event_id}: {str(e)}")
                    self.state.increment_errors()
                    
        except Exception as e:
            logger.error(f"Failed to submit events: {str(e)}")
    
    def _check_admin_commands(self) -> None:
        """Check for and execute pending admin commands."""
        if not self.config.has_graph_configuration():
            return
        try:
            graph_client = self._get_graph_client()
            
            # Authenticate if needed
            if not graph_client.is_authenticated():
                if not graph_client.authenticate():
                    logger.warning("Graph authentication failed, will retry later")
                    return
            
            # Get pending commands
            commands = graph_client.get_pending_commands(self.config.workstation_id)
            
            for command in commands:
                try:
                    logger.info(f"Executing command: {command.command_id} ({command.command_type.value})")
                    
                    # Convert command to dict for handler
                    command_dict = {
                        "command_type": command.command_type.value,
                        "target_workstation_id": command.target_workstation_id,
                        "target_windows_session_id": command.target_windows_session_id,
                        "requested_by_upn": command.requested_by_upn,
                        "requested_by_object_id": command.requested_by_object_id,
                        "reason": command.reason,
                    }
                    
                    # Execute command
                    success, message = self.command_handler.execute_command(command_dict)
                    
                    # Update command status
                    status = CommandStatus.EXECUTED.value if success else CommandStatus.FAILED.value
                    graph_client.update_command_status(
                        command,
                        status,
                        message,
                    )
                    
                    self.state.increment_commands_executed()
                    logger.info(f"Command completed: {command.command_id} - {status}")
                    
                except Exception as e:
                    logger.error(f"Failed to execute command {command.command_id}: {str(e)}")
                    self.state.increment_errors()
                    
        except Exception as e:
            logger.error(f"Failed to check admin commands: {str(e)}")
    
    def _update_status(self) -> None:
        """Update workstation status in SharePoint."""
        if not self.config.has_graph_configuration():
            return
        try:
            graph_client = self._get_graph_client()
            
            # Authenticate if needed
            if not graph_client.is_authenticated():
                if not graph_client.authenticate():
                    logger.warning("Graph authentication failed, will retry later")
                    return
            
            # Update status
            success = graph_client.update_workstation_status(
                workstation_id=self.config.workstation_id,
                agent_status=self.state.status,
                current_session_state=self.state.current_session_state,
                current_session_user=self.state.current_session_user,
                current_windows_session_id=self.state.current_windows_session_id,
                agent_version=self.config.agent_version,
            )
            
            if success:
                self.state.last_status_update_time = datetime.now(timezone.utc)
                logger.debug("Workstation status updated")
            else:
                logger.warning("Failed to update workstation status")
                
        except Exception as e:
            logger.error(f"Failed to update status: {str(e)}")
    
    def _sync_with_portal(self) -> None:
        """Perform initial synchronization with the portal."""
        try:
            logger.info("Starting initial synchronization with portal...")
            
            # Get workstation info from portal
            graph_client = self._get_graph_client()
            
            if graph_client.authenticate():
                workstation = graph_client.get_workstation(self.config.workstation_id)
                
                if workstation:
                    # Update our state from portal
                    self.state.manual_flag_type = workstation.manual_flag.flag_type
                    self.state.current_session_state = workstation.current_session_state
                    self.state.current_session_user = workstation.current_session_user
                    self.state.current_windows_session_id = workstation.current_windows_session_id
                    
                    logger.info(f"Synchronized with portal: {self.config.workstation_id}")
                else:
                    logger.warning(f"Workstation not found in portal: {self.config.workstation_id}")
            else:
                logger.warning("Graph authentication failed during initial sync")
                
        except Exception as e:
            logger.error(f"Initial sync failed: {str(e)}")
    
    def _cleanup_old_events(self) -> None:
        """Clean up old events from the queue."""
        try:
            queue = self._get_event_queue()
            removed = queue.cleanup_old_events()
            if removed > 0:
                logger.debug(f"Cleaned up {removed} old events")
        except Exception as e:
            logger.error(f"Failed to cleanup old events: {str(e)}")
    
    def run(self) -> None:
        """Run the agent main loop.
        
        This method runs the agent until stopped.
        """
        if not self.start():
            return
        
        logger.info(f"Agent main loop started: {self.config.workstation_id}")
        
        while self._running:
            try:
                # Perform polling cycle
                self.poll()
                
                # Sleep for the configured interval
                time.sleep(self.config.poll_interval)
                
            except KeyboardInterrupt:
                logger.info("Agent interrupted by user")
                self.stop()
                break
            except Exception as e:
                logger.error(f"Agent error: {str(e)}")
                time.sleep(5)  # Wait before retrying
        
        logger.info("Agent main loop stopped")


# =============================================================================
# Windows Service Implementation
# =============================================================================

class RDPWorkstationAgentService(win32serviceutil.ServiceFramework):
    """Windows Service for RDP Workstation Agent."""
    
    _svc_name_ = "RDPWorkstationAgent"
    _svc_display_name_ = "Kirschke RDP Workstation Agent"
    _svc_description_ = "Monitors RDP sessions and communicates with Kirschke RDP Portal"
    
    def __init__(self, args):
        """Initialize the service."""
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.agent = None
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
    
    def SvcDoRun(self):
        """Service main loop."""
        import servicemanager
        
        try:
            # Initialize agent
            config = AgentConfig.from_env()
            self.agent = WorkstationAgent(config)
            
            if not self.agent.start():
                servicemanager.LogErrorMsg(f"Failed to start agent: {config.workstation_id}")
                return
            
            servicemanager.LogInfoMsg(f"Agent service started: {config.workstation_id}")
            
            # Run the agent
            while True:
                # Perform polling cycle
                self.agent.poll()
                
                # Wait for poll interval or stop signal
                wait_result = win32event.WaitForSingleObject(
                    self._stop_event,
                    config.poll_interval * 1000
                )
                
                if wait_result == win32event.WAIT_OBJECT_0:
                    # Stop signal received
                    break
            
        except Exception as e:
            servicemanager.LogErrorMsg(f"Service error: {str(e)}")
        finally:
            if self.agent:
                self.agent.stop()
            servicemanager.LogInfoMsg("Agent service stopped")
    
    def SvcStop(self):
        """Stop the service."""
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)
    
    def SvcPause(self):
        """Pause the service."""
        self.ReportServiceStatus(win32service.SERVICE_PAUSED)
    
    def SvcContinue(self):
        """Continue the service."""
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
    
    def SvcShutdown(self):
        """Handle system shutdown."""
        self.SvcStop()


# =============================================================================
# Main Entry Points
# =============================================================================

def main():
    """Main entry point for command-line execution."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Kirschke RDP Workstation Agent"
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install as Windows service",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Uninstall Windows service",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the service",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the service",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run in console mode",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the current local WTS/RDP status as JSON and exit",
    )
    
    args = parser.parse_args()
    
    # Set debug logging if requested
    if args.debug:
        os.environ["AGENT_LOG_LEVEL"] = "DEBUG"

    if args.status:
        from workstation_agent.wts.monitor import WTSMonitor

        config = AgentConfig.from_env()
        with WTSMonitor() as monitor:
            sessions = monitor.get_rdp_sessions()
            primary = monitor.get_primary_rdp_session()
        result = {
            "workstation_id": config.workstation_id,
            "hostname": config.hostname,
            "agent_version": config.agent_version,
            "session_state": primary.session_state.value if primary else SessionState.NONE.value,
            "session_user": primary.full_username if primary else None,
            "windows_session_id": primary.session_id if primary else None,
            "rdp_sessions": [session.to_dict() for session in sessions],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    
    # Handle service commands
    if args.install:
        # Install service
        config = AgentConfig.from_env()
        service_class = RDPWorkstationAgentService
        
        # Set service name with workstation ID
        service_class._svc_name_ = f"RDPWorkstationAgent_{config.workstation_id}"
        service_class._svc_display_name_ = f"Kirschke RDP Agent - {config.workstation_id}"
        
        win32serviceutil.InstallService(
            service_class._svc_name_,
            service_class._svc_display_name_,
            service_class._svc_description_,
            executable=sys.executable,
            startType=win32service.SERVICE_AUTO_START,
            errorControl=win32service.SERVICE_ERROR_NORMAL,
        )
        print(f"Service installed: {service_class._svc_name_}")
        return
    
    if args.uninstall:
        config = AgentConfig.from_env()
        service_name = f"RDPWorkstationAgent_{config.workstation_id}"
        win32serviceutil.RemoveService(service_name)
        print(f"Service uninstalled: {service_name}")
        return
    
    if args.start:
        config = AgentConfig.from_env()
        service_name = f"RDPWorkstationAgent_{config.workstation_id}"
        win32serviceutil.StartService(service_name)
        print(f"Service started: {service_name}")
        return
    
    if args.stop:
        config = AgentConfig.from_env()
        service_name = f"RDPWorkstationAgent_{config.workstation_id}"
        win32serviceutil.StopService(service_name)
        print(f"Service stopped: {service_name}")
        return
    
    # Run in console mode
    if args.run or not any([args.install, args.uninstall, args.start, args.stop]):
        config = AgentConfig.from_env()
        agent = WorkstationAgent(config)
        
        try:
            agent.run()
        except KeyboardInterrupt:
            agent.stop()


if __name__ == "__main__":
    main()


__all__ = [
    "AgentConfig",
    "AgentState",
    "CommandHandler",
    "WorkstationAgent",
    "RDPWorkstationAgentService",
    "main",
]
