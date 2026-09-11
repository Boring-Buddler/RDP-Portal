"""Bounded, authenticated Windows named-pipe status protocol. No command execution."""
import time

PIPE_NAME = "KirschkeRDPStatus-v1"
MAX_MESSAGE = 65536
# Read/write data and attributes, without FILE_CREATE_PIPE_INSTANCE (0x4).
CLIENT_ACCESS = 0x00120183


def io_operation(handle, operation, timeout_ms=5000):
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


def read_message(handle, size=MAX_MESSAGE):
    import win32file
    return io_operation(handle, lambda ov: win32file.ReadFile(handle, size, ov)[1])


def write_message(handle, data):
    import win32file
    def operation(ov):
        win32file.WriteFile(handle, data, ov)
    count = io_operation(handle, operation)
    if count != len(data):
        raise OSError("Unvollständige Agent-Nachricht")


def request_snapshot(target, pipe_name=PIPE_NAME):
    import json
    import re
    import win32con
    import win32file
    import win32pipe
    from shared.agent_snapshot import AgentSnapshot
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", target) or target in (".", ".."):
        raise ValueError("Für die Live-Abfrage einen Hostnamen oder eine IPv4-Adresse verwenden.")
    path = rf"\\{target}\pipe\{pipe_name}"
    started = time.monotonic()
    win32pipe.WaitNamedPipe(path, 1500)
    handle = win32file.CreateFile(path, CLIENT_ACCESS, 0, None, win32con.OPEN_EXISTING,
                                win32con.FILE_FLAG_OVERLAPPED | 0x00100000, None)  # SECURITY_SQOS_PRESENT, anonymous
    try:
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        write_message(handle, b"STATUS/1")
        raw = read_message(handle)
        write_message(handle, b"OK")
        data = json.loads(raw)
        if "error" in data:
            raise ValueError("Der Agent konnte den Windows-Sitzungsstatus nicht lesen.")
        return AgentSnapshot.from_dict(data), round((time.monotonic() - started) * 1000)
    finally:
        handle.Close()
