"""Windows Terminal Services (WTS) monitoring for Kirschke RDP Workstation Portal.

This module provides functionality to monitor RDP sessions on a Windows workstation
using the Windows Terminal Services API (WTSAPI32.dll).

Features:
- Enumerate active RDP sessions
- Get session information (user, state, connection time)
- Detect session state changes (logon, logoff, disconnect, reconnect)
- Monitor session events in real-time
"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Any

from shared.enums import SessionState

logger = logging.getLogger(__name__)


# =============================================================================
# Windows API Constants
# =============================================================================

# WTS session states
WTS_CONSOLE_CONNECT = 0x0
WTS_CONSOLE_DISCONNECT = 0x1
WTS_REMOTE_CONNECT = 0x2
WTS_REMOTE_DISCONNECT = 0x3
WTS_SESSION_LOGON = 0x4
WTS_SESSION_LOGOFF = 0x5
WTS_SESSION_LOCK = 0x6
WTS_SESSION_UNLOCK = 0x7
WTS_SESSION_REMOTE_CONTROL = 0x8

# WTS session information classes
WTS_INFO_CLASS = Enum("WTS_INFO_CLASS", {
    "WTSInitialProgram": 0,
    "WTSApplicationName": 1,
    "WTSWorkingDirectory": 2,
    "WTSOEMId": 3,
    "WTSSessionId": 4,
    "WTSUserName": 5,
    "WTSWinStationName": 6,
    "WTSDomainName": 7,
    "WTSConnectState": 8,
    "WTSClientBuildNumber": 9,
    "WTSClientName": 10,
    "WTSClientDisplay": 11,
    "WTSClientHardwareId": 12,
    "WTSClientAddress": 13,
    "WTSClientDisplayResolution": 14,
    "TSUserConfig": 15,
})

# WTS connect states
WTS_CONNECTSTATE_CLASS = Enum("WTS_CONNECTSTATE_CLASS", {
    "WTSActive": 0,
    "WTSConnected": 1,
    "WTSConnectQuery": 2,
    "WTSShadow": 3,
    "WTSDisconnected": 4,
    "WTSIdle": 5,
    "WTSListen": 6,
    "WTSReset": 7,
    "WTSDown": 8,
    "WTSInit": 9,
})


# =============================================================================
# Windows API Functions
# =============================================================================

# Load WTSAPI32.dll
wtsapi32 = ctypes.windll.Wtsapi32

# Define function prototypes
wtsapi32.WTSOpenServerA.argtypes = [ctypes.c_char_p]
wtsapi32.WTSOpenServerA.restype = ctypes.c_void_p

wtsapi32.WTSCloseServer.argtypes = [ctypes.c_void_p]
wtsapi32.WTSCloseServer.restype = None

wtsapi32.WTSQueryUserToken.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p)]
wtsapi32.WTSQueryUserToken.restype = ctypes.c_bool

wtsapi32.WTSEnumerateSessionsA.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_ulong),
]
wtsapi32.WTSEnumerateSessionsA.restype = ctypes.c_bool

wtsapi32.WTSQuerySessionInformationA.argtypes = [
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_ulong),
]
wtsapi32.WTSQuerySessionInformationA.restype = ctypes.c_bool

wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
wtsapi32.WTSFreeMemory.restype = None


# =============================================================================
# Session Information
# =============================================================================

@dataclass
class WTSSessionInfo:
    """Information about a Windows Terminal Services session."""
    
    session_id: int
    username: Optional[str] = None
    domain: Optional[str] = None
    display_name: Optional[str] = None
    client_name: Optional[str] = None
    client_address: Optional[str] = None
    connect_state: Optional[WTS_CONNECTSTATE_CLASS] = None
    session_state: SessionState = SessionState.NONE
    login_time: Optional[datetime] = None
    last_input_time: Optional[datetime] = None
    is_console_session: bool = False
    
    @property
    def full_username(self) -> str:
        """Get full username with domain."""
        if self.domain and self.username:
            return f"{self.domain}\\n{self.username}"
        return self.username or ""
    
    @property
    def is_rdp_session(self) -> bool:
        """Check if this is an RDP session (not console)."""
        return not self.is_console_session
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "username": self.username,
            "domain": self.domain,
            "display_name": self.display_name,
            "client_name": self.client_name,
            "client_address": self.client_address,
            "connect_state": self.connect_state.name if self.connect_state else None,
            "session_state": self.session_state.value,
            "login_time": self.login_time.isoformat() if self.login_time else None,
            "last_input_time": self.last_input_time.isoformat() if self.last_input_time else None,
            "is_console_session": self.is_console_session,
        }


# =============================================================================
# WTS Monitor
# =============================================================================

class WTSMonitor:
    """Monitor for Windows Terminal Services sessions.
    
    This class provides methods to enumerate and monitor RDP sessions on a Windows
    workstation using the WTSAPI32 library.
    
    Example usage:
        monitor = WTSMonitor()
        sessions = monitor.get_active_sessions()
        for session in sessions:
            print(f"Session {session.session_id}: {session.username}")
    """
    
    def __init__(self, server_name: Optional[str] = None):
        """Initialize the WTS monitor.
        
        Args:
            server_name: Optional server name. If None, uses local machine.
        """
        self.server_name = server_name
        self._server_handle: Optional[ctypes.c_void_p] = None
        self._open_server()
    
    def _open_server(self) -> None:
        """Open connection to WTS server."""
        try:
            if self.server_name:
                self._server_handle = wtsapi32.WTSOpenServerA(self.server_name.encode("utf-8"))
            else:
                self._server_handle = wtsapi32.WTSOpenServerA(None)
            
            if not self._server_handle:
                raise RuntimeError("Failed to open WTS server handle")
        except Exception as e:
            logger.error(f"Failed to open WTS server: {e}")
            raise
    
    def close(self) -> None:
        """Close connection to WTS server."""
        if self._server_handle:
            try:
                wtsapi32.WTSCloseServer(self._server_handle)
                self._server_handle = None
            except Exception as e:
                logger.warning(f"Failed to close WTS server: {e}")
    
    def __enter__(self) -> "WTSMonitor":
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
    
    def _get_session_info(self, session_id: int) -> Optional[WTSSessionInfo]:
        """Get information about a specific session.
        
        Args:
            session_id: Windows session ID
            
        Returns:
            WTSSessionInfo if session exists, None otherwise
        """
        if not self._server_handle:
            return None
        
        info = WTSSessionInfo(session_id=session_id)
        
        # Get username
        username_ptr = ctypes.c_void_p()
        username_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSUserName.value,
            ctypes.byref(username_ptr),
            ctypes.byref(username_len),
        ):
            username = ctypes.cast(username_ptr, ctypes.c_char_p).value
            info.username = username.decode("utf-8") if username else None
            wtsapi32.WTSFreeMemory(username_ptr)
        
        # Get domain
        domain_ptr = ctypes.c_void_p()
        domain_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSDomainName.value,
            ctypes.byref(domain_ptr),
            ctypes.byref(domain_len),
        ):
            domain = ctypes.cast(domain_ptr, ctypes.c_char_p).value
            info.domain = domain.decode("utf-8") if domain else None
            wtsapi32.WTSFreeMemory(domain_ptr)
        
        # Get display name
        display_ptr = ctypes.c_void_p()
        display_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSWinStationName.value,
            ctypes.byref(display_ptr),
            ctypes.byref(display_len),
        ):
            display = ctypes.cast(display_ptr, ctypes.c_char_p).value
            info.display_name = display.decode("utf-8") if display else None
            wtsapi32.WTSFreeMemory(display_ptr)
        
        # Get client name
        client_ptr = ctypes.c_void_p()
        client_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSClientName.value,
            ctypes.byref(client_ptr),
            ctypes.byref(client_len),
        ):
            client = ctypes.cast(client_ptr, ctypes.c_char_p).value
            info.client_name = client.decode("utf-8") if client else None
            wtsapi32.WTSFreeMemory(client_ptr)
        
        # Get client address
        addr_ptr = ctypes.c_void_p()
        addr_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSClientAddress.value,
            ctypes.byref(addr_ptr),
            ctypes.byref(addr_len),
        ):
            addr = ctypes.cast(addr_ptr, ctypes.c_char_p).value
            info.client_address = addr.decode("utf-8") if addr else None
            wtsapi32.WTSFreeMemory(addr_ptr)
        
        # Get connect state
        state_ptr = ctypes.c_void_p()
        state_len = ctypes.c_ulong()
        if wtsapi32.WTSQuerySessionInformationA(
            self._server_handle,
            session_id,
            WTS_INFO_CLASS.WTSConnectState.value,
            ctypes.byref(state_ptr),
            ctypes.byref(state_len),
        ):
            state = ctypes.cast(state_ptr, ctypes.c_ulong).value
            info.connect_state = WTS_CONNECTSTATE_CLASS(state)
            wtsapi32.WTSFreeMemory(state_ptr)
        
        # Determine session state
        info.session_state = self._map_connect_state_to_session_state(info.connect_state)
        
        # Check if console session (session 0 is typically console)
        info.is_console_session = session_id == 0
        
        return info
    
    def _map_connect_state_to_session_state(
        self, connect_state: Optional[WTS_CONNECTSTATE_CLASS]
    ) -> SessionState:
        """Map WTS connect state to portal session state.
        
        Args:
            connect_state: WTS connect state
            
        Returns:
            Corresponding SessionState
        """
        if connect_state is None:
            return SessionState.NONE
        
        state_mapping = {
            WTS_CONNECTSTATE_CLASS.WTSActive: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSConnected: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSConnectQuery: SessionState.LOGON,
            WTS_CONNECTSTATE_CLASS.WTSShadow: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSDisconnected: SessionState.DISCONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSIdle: SessionState.DISCONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSListen: SessionState.NONE,
            WTS_CONNECTSTATE_CLASS.WTSReset: SessionState.NONE,
            WTS_CONNECTSTATE_CLASS.WTSDown: SessionState.NONE,
            WTS_CONNECTSTATE_CLASS.WTSInit: SessionState.NONE,
        }
        
        return state_mapping.get(connect_state, SessionState.NONE)
    
    def get_all_sessions(self) -> list[WTSSessionInfo]:
        """Get information about all active sessions.
        
        Returns:
            List of WTSSessionInfo for all sessions
        """
        if not self._server_handle:
            return []
        
        sessions: list[WTSSessionInfo] = []
        
        try:
            # Enumerate sessions
            session_ids_ptr = ctypes.c_void_p()
            session_count = ctypes.c_ulong()
            
            if wtsapi32.WTSEnumerateSessionsA(
                self._server_handle,
                0,
                1,
                ctypes.byref(session_ids_ptr),
                ctypes.byref(session_count),
            ):
                # Cast to array of session IDs
                session_ids = ctypes.cast(
                    session_ids_ptr,
                    ctypes.POINTER(ctypes.c_ulong * session_count.value)
                ).contents
                
                # Get info for each session
                for i in range(session_count.value):
                    session_id = session_ids[i]
                    info = self._get_session_info(session_id)
                    if info:
                        sessions.append(info)
                
                wtsapi32.WTSFreeMemory(session_ids_ptr)
        except Exception as e:
            logger.error(f"Failed to enumerate sessions: {e}")
        
        return sessions
    
    def get_rdp_sessions(self) -> list[WTSSessionInfo]:
        """Get only RDP (non-console) sessions.
        
        Returns:
            List of WTSSessionInfo for RDP sessions only
        """
        all_sessions = self.get_all_sessions()
        return [s for s in all_sessions if s.is_rdp_session]
    
    def get_active_rdp_sessions(self) -> list[WTSSessionInfo]:
        """Get active RDP sessions.
        
        Returns:
            List of WTSSessionInfo for active RDP sessions
        """
        rdp_sessions = self.get_rdp_sessions()
        return [
            s for s in rdp_sessions
            if s.connect_state in [
                WTS_CONNECTSTATE_CLASS.WTSActive,
                WTS_CONNECTSTATE_CLASS.WTSConnected,
            ]
        ]
    
    def get_session(self, session_id: int) -> Optional[WTSSessionInfo]:
        """Get information about a specific session.
        
        Args:
            session_id: Session ID to query
            
        Returns:
            WTSSessionInfo if session exists, None otherwise
        """
        return self._get_session_info(session_id)
    
    def get_current_session_id(self) -> int:
        """Get the current session ID.
        
        Returns:
            Current session ID
        """
        import os
        return os.getppid()  # Process ID is the session ID for current process
    
    def get_current_session(self) -> Optional[WTSSessionInfo]:
        """Get information about the current session.
        
        Returns:
            WTSSessionInfo for current session, or None
        """
        session_id = self.get_current_session_id()
        return self.get_session(session_id)
    
    def has_rdp_sessions(self) -> bool:
        """Check if there are any active RDP sessions.
        
        Returns:
            True if there are active RDP sessions
        """
        return len(self.get_active_rdp_sessions()) > 0
    
    def get_first_rdp_session(self) -> Optional[WTSSessionInfo]:
        """Get the first active RDP session.
        
        Returns:
            First active RDP session, or None
        """
        sessions = self.get_active_rdp_sessions()
        return sessions[0] if sessions else None


# =============================================================================
# Session Change Notifications
# =============================================================================

class SessionChangeNotifier:
    """Monitor for session state changes.
    
    This class can be used to detect when RDP sessions are started, ended,
    or state changes occur.
    """
    
    def __init__(self, monitor: Optional[WTSMonitor] = None):
        """Initialize the session change notifier.
        
        Args:
            monitor: Optional WTSMonitor instance
        """
        self.monitor = monitor or WTSMonitor()
        self._last_session_states: dict[int, WTS_CONNECTSTATE_CLASS] = {}
    
    def check_for_changes(self) -> dict[int, tuple[WTS_CONNECTSTATE_CLASS, WTS_CONNECTSTATE_CLASS]]:
        """Check for session state changes since last check.
        
        Returns:
            Dictionary mapping session IDs to (old_state, new_state) tuples
        """
        changes: dict[int, tuple[WTS_CONNECTSTATE_CLASS, WTS_CONNECTSTATE_CLASS]] = {}
        
        current_sessions = self.monitor.get_all_sessions()
        
        for session in current_sessions:
            session_id = session.session_id
            new_state = session.connect_state
            old_state = self._last_session_states.get(session_id)
            
            if old_state != new_state:
                changes[session_id] = (old_state, new_state)
                self._last_session_states[session_id] = new_state
        
        # Check for sessions that disappeared
        for session_id in list(self._last_session_states.keys()):
            if session_id not in [s.session_id for s in current_sessions]:
                old_state = self._last_session_states.pop(session_id)
                changes[session_id] = (old_state, None)
        
        return changes
    
    def get_session_changes(self) -> list[dict[str, Any]]:
        """Get a list of session changes with human-readable information.
        
        Returns:
            List of change dictionaries
        """
        changes = self.check_for_changes()
        
        result = []
        for session_id, (old_state, new_state) in changes.items():
            change = {
                "session_id": session_id,
                "old_state": old_state.name if old_state else None,
                "new_state": new_state.name if new_state else None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            # Determine change type
            if old_state is None and new_state is not None:
                change["change_type"] = "SESSION_STARTED"
            elif old_state is not None and new_state is None:
                change["change_type"] = "SESSION_ENDED"
            elif old_state != new_state:
                change["change_type"] = "SESSION_STATE_CHANGED"
            else:
                change["change_type"] = "UNKNOWN"
            
            # Get session info
            session = self.monitor.get_session(session_id)
            if session:
                change["username"] = session.username
                change["domain"] = session.domain
                change["client_name"] = session.client_name
            
            result.append(change)
        
        return result


# =============================================================================
# Factory and Exports
# =============================================================================

def get_wts_monitor() -> WTSMonitor:
    """Get a WTSMonitor instance.
    
    Returns:
        WTSMonitor instance
    """
    return WTSMonitor()


def get_session_change_notifier() -> SessionChangeNotifier:
    """Get a SessionChangeNotifier instance.
    
    Returns:
        SessionChangeNotifier instance
    """
    return SessionChangeNotifier()


__all__ = [
    "WTS_CONNECTSTATE_CLASS",
    "WTSSessionInfo",
    "WTSMonitor",
    "SessionChangeNotifier",
    "get_wts_monitor",
    "get_session_change_notifier",
]
