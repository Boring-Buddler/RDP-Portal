"""Bounded Windows named-pipe protocol for status and verified local logoff."""
import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

PIPE_NAME = "KirschkeRDPStatus-v1"
MAX_MESSAGE = 65536
#: Wie lange auf eine Agent-Antwort gewartet wird.  Fuer STATUS/1 reicht das
#: reichlich, denn der Agent liest nur WTS aus.
DEFAULT_TIMEOUT_MS = 5000
#: LOGOFF/1 antwortet erst, wenn WTSLogoffSession mit bWait=TRUE zurueckkommt --
#: also nachdem Windows die Sitzung vollstaendig abgebaut hat.  Das dauert
#: regelmaessig laenger als fuenf Sekunden; mit dem alten Standardwert lief die
#: erfolgreiche Abmeldung in einen TimeoutError und wurde als Fehler gemeldet.
LOGOFF_TIMEOUT_MS = 45000
# Read/write data and attributes, without FILE_CREATE_PIPE_INSTANCE (0x4).
CLIENT_ACCESS = 0x00120183


def io_operation(handle, operation, timeout_ms=DEFAULT_TIMEOUT_MS):
    import pywintypes
    import win32event
    import win32file
    overlap = pywintypes.OVERLAPPED()
    overlap.hEvent = win32event.CreateEvent(None, True, False, None)
    try:
        buffer = operation(overlap)
        if win32event.WaitForSingleObject(overlap.hEvent, timeout_ms) != win32event.WAIT_OBJECT_0:
            # Each handle has one outstanding operation, issued by this thread.
            win32file.CancelIo(handle)
            try:
                win32file.GetOverlappedResult(handle, overlap, True)
            except pywintypes.error:
                pass
            raise TimeoutError("Keine rechtzeitige Antwort vom Agenten.")
        count = win32file.GetOverlappedResult(handle, overlap, False)
        return bytes(buffer[:count]) if buffer is not None else count
    finally:
        overlap.hEvent.Close()


def read_message(handle, size=MAX_MESSAGE, timeout_ms=DEFAULT_TIMEOUT_MS):
    import win32file
    return io_operation(handle, lambda ov: win32file.ReadFile(handle, size, ov)[1], timeout_ms)


def write_message(handle, data):
    import win32file
    def operation(ov):
        win32file.WriteFile(handle, data, ov)
    count = io_operation(handle, operation)
    if count != len(data):
        raise OSError("Unvollständige Agent-Nachricht")


def _open_pipe(target, pipe_name):
    import win32con
    import win32file
    import win32pipe
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", target) or target in (".", ".."):
        raise ValueError("Für die Live-Abfrage einen Hostnamen oder eine IPv4-Adresse verwenden.")
    path = rf"\\{target}\pipe\{pipe_name}"
    win32pipe.WaitNamedPipe(path, 1500)
    handle = win32file.CreateFile(
        path,
        CLIENT_ACCESS,
        0,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_FLAG_OVERLAPPED | 0x00100000 | 0x00020000,
        None,
    )  # SECURITY_SQOS_PRESENT | SECURITY_IMPERSONATION
    win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
    return handle


@contextmanager
def _network_credentials(credentials):
    """Use explicit target credentials only on the current worker thread."""
    if not credentials:
        yield
        return
    import win32con
    import win32security
    username, password = credentials
    domain, separator, account = username.partition("\\")
    if not separator:
        domain, account = ".", username
    if not domain or not account or not password:
        raise ValueError("Windows-Administratorkonto und Kennwort fehlen.")
    token = win32security.LogonUser(
        account,
        domain,
        password,
        win32con.LOGON32_LOGON_NEW_CREDENTIALS,
        win32con.LOGON32_PROVIDER_WINNT50,
    )
    try:
        win32security.ImpersonateLoggedOnUser(token)
        yield
    finally:
        win32security.RevertToSelf()
        token.Close()


def _exchange(target, request, pipe_name=PIPE_NAME, credentials=None,
              response_timeout_ms=DEFAULT_TIMEOUT_MS):
    with _network_credentials(credentials):
        handle = _open_pipe(target, pipe_name)
        try:
            write_message(handle, request)
            raw = read_message(handle, timeout_ms=response_timeout_ms)
            write_message(handle, b"OK")
            return json.loads(raw)
        finally:
            handle.Close()


def request_snapshot(target, pipe_name=PIPE_NAME):
    from shared.agent_snapshot import AgentSnapshot
    started = time.monotonic()
    data = _exchange(target, b"STATUS/1", pipe_name)
    if "error" in data:
        raise ValueError("Der Agent konnte den Windows-Sitzungsstatus nicht lesen.")
    return AgentSnapshot.from_dict(data), round((time.monotonic() - started) * 1000)


def request_agent_logoff(
    target,
    session_id,
    username,
    login_time,
    requester_identity,
    expected_agent_id=None,
    *,
    administrative=False,
    credentials=None,
    pipe_name=PIPE_NAME,
):
    """Ask the SYSTEM agent to validate and locally end one exact session."""
    request = {
        "protocol": "LOGOFF/1",
        "request_id": str(uuid.uuid4()),
        "requested_at_utc": datetime.now(UTC).isoformat(),
        "session_id": session_id,
        "username": username,
        "login_time": login_time,
        "requester_identity": requester_identity,
        "expected_agent_id": expected_agent_id,
        "administrative": bool(administrative),
    }
    data = _exchange(
        target,
        (b"LOGOFF/1 " + json.dumps(request, separators=(",", ":")).encode("utf-8")),
        pipe_name,
        credentials,
        response_timeout_ms=LOGOFF_TIMEOUT_MS,
    )
    if not data.get("ok"):
        raise PermissionError(data.get("message") or "Der Agent hat die Abmeldung abgelehnt.")
    return data.get("message") or "Der Agent hat die Sitzung abgemeldet."
