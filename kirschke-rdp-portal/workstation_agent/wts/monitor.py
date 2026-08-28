"""Reliable Windows Terminal Services session discovery for the workstation agent."""

from __future__ import annotations

import ctypes
import logging
import os
import socket
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

from shared.enums import SessionState

logger = logging.getLogger(__name__)


class WTS_INFO_CLASS(IntEnum):
    """Subset of WTS_INFO_CLASS used by the agent."""

    WTSSessionId = 4
    WTSUserName = 5
    WTSWinStationName = 6
    WTSDomainName = 7
    WTSConnectState = 8
    WTSClientName = 10
    WTSClientAddress = 14
    WTSClientProtocolType = 16


class WTS_CONNECTSTATE_CLASS(IntEnum):
    WTSActive = 0
    WTSConnected = 1
    WTSConnectQuery = 2
    WTSShadow = 3
    WTSDisconnected = 4
    WTSIdle = 5
    WTSListen = 6
    WTSReset = 7
    WTSDown = 8
    WTSInit = 9


class WTS_SESSION_INFOW(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


class WTS_CLIENT_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("AddressFamily", wintypes.DWORD),
        ("Address", ctypes.c_ubyte * 20),
    ]


WTS_CURRENT_SERVER_HANDLE = wintypes.HANDLE(0)
NO_CONSOLE_SESSION = 0xFFFFFFFF
AF_INET = 2
AF_INET6 = 23

wtsapi32 = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

wtsapi32.WTSOpenServerW.argtypes = [wintypes.LPWSTR]
wtsapi32.WTSOpenServerW.restype = wintypes.HANDLE
wtsapi32.WTSCloseServer.argtypes = [wintypes.HANDLE]
wtsapi32.WTSCloseServer.restype = None
wtsapi32.WTSEnumerateSessionsW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(WTS_SESSION_INFOW)),
    ctypes.POINTER(wintypes.DWORD),
]
wtsapi32.WTSEnumerateSessionsW.restype = wintypes.BOOL
wtsapi32.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(wintypes.DWORD),
]
wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
wtsapi32.WTSFreeMemory.restype = None
kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
kernel32.WTSGetActiveConsoleSessionId.argtypes = []
kernel32.WTSGetActiveConsoleSessionId.restype = wintypes.DWORD


@dataclass
class WTSSessionInfo:
    """Information about one Windows session."""

    session_id: int
    username: str | None = None
    domain: str | None = None
    display_name: str | None = None
    client_name: str | None = None
    client_address: str | None = None
    connect_state: WTS_CONNECTSTATE_CLASS | None = None
    session_state: SessionState = SessionState.NONE
    protocol_type: int | None = None
    login_time: datetime | None = None
    last_input_time: datetime | None = None
    is_console_session: bool = False

    @property
    def full_username(self) -> str:
        if self.domain and self.username:
            return f"{self.domain}\\{self.username}"
        return self.username or ""

    @property
    def is_rdp_session(self) -> bool:
        if not self.username:
            return False
        station_name = (self.display_name or "").upper()
        return self.protocol_type == 2 or station_name.startswith("RDP-")

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "username": self.username,
            "domain": self.domain,
            "display_name": self.display_name,
            "client_name": self.client_name,
            "client_address": self.client_address,
            "connect_state": self.connect_state.name if self.connect_state is not None else None,
            "session_state": self.session_state.value,
            "protocol_type": self.protocol_type,
            "login_time": self.login_time.isoformat() if self.login_time else None,
            "last_input_time": self.last_input_time.isoformat() if self.last_input_time else None,
            "is_console_session": self.is_console_session,
        }


class WTSMonitor:
    """Enumerate local or remote Windows sessions through WTSAPI32."""

    def __init__(self, server_name: str | None = None) -> None:
        self.server_name = server_name
        self._owns_server_handle = bool(server_name)
        self._server_handle = self._open_server()

    def _open_server(self) -> wintypes.HANDLE:
        if not self.server_name:
            return WTS_CURRENT_SERVER_HANDLE
        handle = wtsapi32.WTSOpenServerW(self.server_name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def close(self) -> None:
        if self._owns_server_handle and self._server_handle is not None:
            wtsapi32.WTSCloseServer(self._server_handle)
        self._server_handle = None

    def __enter__(self) -> WTSMonitor:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _query_buffer(self, session_id: int, info_class: WTS_INFO_CLASS) -> tuple[int, int] | None:
        if self._server_handle is None:
            return None
        buffer = ctypes.c_void_p()
        byte_count = wintypes.DWORD()
        success = wtsapi32.WTSQuerySessionInformationW(
            self._server_handle,
            session_id,
            int(info_class),
            ctypes.byref(buffer),
            ctypes.byref(byte_count),
        )
        if not success or not buffer.value:
            return None
        return buffer.value, byte_count.value

    @staticmethod
    def _free_buffer(address: int) -> None:
        wtsapi32.WTSFreeMemory(ctypes.c_void_p(address))

    def _query_text(self, session_id: int, info_class: WTS_INFO_CLASS) -> str | None:
        result = self._query_buffer(session_id, info_class)
        if result is None:
            return None
        address, _ = result
        try:
            value = ctypes.wstring_at(address)
            return value or None
        finally:
            self._free_buffer(address)

    def _query_number(
        self,
        session_id: int,
        info_class: WTS_INFO_CLASS,
        ctype,
    ) -> int | None:
        result = self._query_buffer(session_id, info_class)
        if result is None:
            return None
        address, _ = result
        try:
            return int(ctypes.cast(address, ctypes.POINTER(ctype)).contents.value)
        finally:
            self._free_buffer(address)

    def _query_client_address(self, session_id: int) -> str | None:
        result = self._query_buffer(session_id, WTS_INFO_CLASS.WTSClientAddress)
        if result is None:
            return None
        address, _ = result
        try:
            client = ctypes.cast(address, ctypes.POINTER(WTS_CLIENT_ADDRESS)).contents
            raw = bytes(client.Address)
            if client.AddressFamily == AF_INET:
                return socket.inet_ntop(socket.AF_INET, raw[2:6])
            if client.AddressFamily == AF_INET6:
                return socket.inet_ntop(socket.AF_INET6, raw[:16])
            return None
        finally:
            self._free_buffer(address)

    @staticmethod
    def _map_connect_state_to_session_state(
        connect_state: WTS_CONNECTSTATE_CLASS | None,
    ) -> SessionState:
        state_mapping = {
            WTS_CONNECTSTATE_CLASS.WTSActive: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSConnected: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSConnectQuery: SessionState.LOGON,
            WTS_CONNECTSTATE_CLASS.WTSShadow: SessionState.CONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSDisconnected: SessionState.DISCONNECTED,
            WTS_CONNECTSTATE_CLASS.WTSIdle: SessionState.DISCONNECTED,
        }
        return state_mapping.get(connect_state, SessionState.NONE)

    def _get_session_info(
        self,
        session_id: int,
        connect_state: WTS_CONNECTSTATE_CLASS | None = None,
        station_name: str | None = None,
    ) -> WTSSessionInfo:
        if connect_state is None:
            raw_state = self._query_number(
                session_id,
                WTS_INFO_CLASS.WTSConnectState,
                wintypes.DWORD,
            )
            try:
                connect_state = WTS_CONNECTSTATE_CLASS(raw_state) if raw_state is not None else None
            except ValueError:
                connect_state = None

        protocol_type = self._query_number(
            session_id,
            WTS_INFO_CLASS.WTSClientProtocolType,
            wintypes.USHORT,
        )
        if station_name is None:
            station_name = self._query_text(session_id, WTS_INFO_CLASS.WTSWinStationName)
        console_session_id = int(kernel32.WTSGetActiveConsoleSessionId())
        return WTSSessionInfo(
            session_id=session_id,
            username=self._query_text(session_id, WTS_INFO_CLASS.WTSUserName),
            domain=self._query_text(session_id, WTS_INFO_CLASS.WTSDomainName),
            display_name=station_name,
            client_name=self._query_text(session_id, WTS_INFO_CLASS.WTSClientName),
            client_address=self._query_client_address(session_id),
            connect_state=connect_state,
            session_state=self._map_connect_state_to_session_state(connect_state),
            protocol_type=protocol_type,
            is_console_session=(
                protocol_type == 0
                or (console_session_id != NO_CONSOLE_SESSION and session_id == console_session_id)
            ),
        )

    def get_all_sessions(self) -> list[WTSSessionInfo]:
        if self._server_handle is None:
            return []
        session_buffer = ctypes.POINTER(WTS_SESSION_INFOW)()
        session_count = wintypes.DWORD()
        success = wtsapi32.WTSEnumerateSessionsW(
            self._server_handle,
            0,
            1,
            ctypes.byref(session_buffer),
            ctypes.byref(session_count),
        )
        if not success:
            error = ctypes.WinError(ctypes.get_last_error())
            logger.error("Failed to enumerate WTS sessions: %s", error)
            return []

        sessions: list[WTSSessionInfo] = []
        try:
            for index in range(session_count.value):
                raw = session_buffer[index]
                try:
                    state = WTS_CONNECTSTATE_CLASS(raw.State)
                except ValueError:
                    state = None
                sessions.append(
                    self._get_session_info(
                        int(raw.SessionId),
                        state,
                        raw.pWinStationName or None,
                    )
                )
        finally:
            if session_buffer:
                wtsapi32.WTSFreeMemory(ctypes.cast(session_buffer, ctypes.c_void_p))
        return sessions

    def get_rdp_sessions(self) -> list[WTSSessionInfo]:
        return [session for session in self.get_all_sessions() if session.is_rdp_session]

    def get_active_rdp_sessions(self) -> list[WTSSessionInfo]:
        return [
            session
            for session in self.get_rdp_sessions()
            if session.session_state in {SessionState.CONNECTED, SessionState.RECONNECTED}
        ]

    def get_primary_rdp_session(self) -> WTSSessionInfo | None:
        priorities = {
            SessionState.CONNECTED: 4,
            SessionState.RECONNECTED: 4,
            SessionState.LOGON: 3,
            SessionState.DISCONNECTED: 2,
        }
        sessions = self.get_rdp_sessions()
        return max(sessions, key=lambda session: priorities.get(session.session_state, 0), default=None)

    def get_session(self, session_id: int) -> WTSSessionInfo | None:
        return self._get_session_info(session_id)

    def get_current_session_id(self) -> int:
        session_id = wintypes.DWORD()
        if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(session_id.value)

    def get_current_session(self) -> WTSSessionInfo | None:
        return self.get_session(self.get_current_session_id())

    def has_rdp_sessions(self) -> bool:
        return bool(self.get_rdp_sessions())

    def get_first_rdp_session(self) -> WTSSessionInfo | None:
        return self.get_primary_rdp_session()


class SessionChangeNotifier:
    """Poll WTS and report new, changed, and disappeared sessions."""

    def __init__(self, monitor: WTSMonitor | None = None) -> None:
        self.monitor = monitor or WTSMonitor()
        self._last_session_states: dict[int, WTS_CONNECTSTATE_CLASS | None] = {}

    def check_for_changes(
        self,
    ) -> dict[int, tuple[WTS_CONNECTSTATE_CLASS | None, WTS_CONNECTSTATE_CLASS | None]]:
        current_sessions = self.monitor.get_all_sessions()
        current_states = {session.session_id: session.connect_state for session in current_sessions}
        changes = {
            session_id: (self._last_session_states.get(session_id), state)
            for session_id, state in current_states.items()
            if self._last_session_states.get(session_id) != state
        }
        for session_id, state in self._last_session_states.items():
            if session_id not in current_states:
                changes[session_id] = (state, None)
        self._last_session_states = current_states
        return changes

    def get_session_changes(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for session_id, (old_state, new_state) in self.check_for_changes().items():
            if old_state is None and new_state is not None:
                change_type = "SESSION_STARTED"
            elif old_state is not None and new_state is None:
                change_type = "SESSION_ENDED"
            else:
                change_type = "SESSION_STATE_CHANGED"
            result.append(
                {
                    "session_id": session_id,
                    "old_state": old_state.name if old_state is not None else None,
                    "new_state": new_state.name if new_state is not None else None,
                    "change_type": change_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        return result


def get_wts_monitor() -> WTSMonitor:
    return WTSMonitor()


def get_session_change_notifier() -> SessionChangeNotifier:
    return SessionChangeNotifier()


__all__ = [
    "WTS_CONNECTSTATE_CLASS",
    "WTSSessionInfo",
    "WTSMonitor",
    "SessionChangeNotifier",
    "get_wts_monitor",
    "get_session_change_notifier",
]
