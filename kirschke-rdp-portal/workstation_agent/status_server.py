"""Read-only live status endpoint protected by Windows pipe ACLs."""
import json
import logging
import threading

from shared.status_pipe import CLIENT_ACCESS, MAX_MESSAGE, PIPE_NAME, io_operation, read_message, write_message

logger = logging.getLogger(__name__)


def security_attributes(reader):
    import pywintypes
    import win32api
    import win32security
    sddl = "D:P(A;;GA;;;SY)(A;;GA;;;BA)"
    if reader:
        try:
            # Resolve only a local account, never an arbitrary remote domain.
            sid, _, _ = win32security.LookupAccountName(None, win32api.GetComputerName() + "\\" + reader)
            sddl += f"(A;;0x{CLIENT_ACCESS:x};;;{win32security.ConvertSidToStringSid(sid)})"
        except pywintypes.error:
            logger.warning("Live-Status: lokales Lesekonto %s fehlt; nur SYSTEM/Administratoren zugelassen", reader)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
    return attributes


class StatusServer(threading.Thread):
    def __init__(self, snapshot_factory, reader="PortalLeser", pipe_name=PIPE_NAME):
        super().__init__(name="agent-live-status", daemon=True)
        self.snapshot_factory = snapshot_factory
        self.reader = reader
        self.pipe_name = pipe_name
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.error = None

    def stop(self):
        self.stopping.set()
        self.join(timeout=6)

    def run(self):
        import pywintypes
        import win32con
        import win32event
        import win32pipe
        handle = None
        try:
            handle = win32pipe.CreateNamedPipe(rf"\\.\pipe\{self.pipe_name}",
                win32pipe.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED | 0x00080000,  # FIRST_PIPE_INSTANCE
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, MAX_MESSAGE, MAX_MESSAGE, 1000, security_attributes(self.reader))
            self.ready.set()
            while not self.stopping.is_set():
                try:
                    def connect(ov):
                        try:
                            win32pipe.ConnectNamedPipe(handle, ov)
                        except pywintypes.error as exc:
                            if exc.winerror != 535:  # Client already connected
                                raise
                            win32event.SetEvent(ov.hEvent)
                    try:
                        io_operation(handle, connect, 1000)
                    except TimeoutError:
                        continue
                    if read_message(handle, 128) != b"STATUS/1":
                        continue
                    try:
                        data = self.snapshot_factory().to_dict()
                    except Exception:
                        logger.exception("Live-Status: WTS-Abfrage fehlgeschlagen")
                        data = {"error": "wts_unavailable"}
                    payload = json.dumps(data).encode("utf-8")
                    if len(payload) > MAX_MESSAGE:
                        payload = b'{"error":"status_too_large"}'
                    write_message(handle, payload)
                    read_message(handle, 128)  # Wait until response consumed, bounded.
                except (OSError, pywintypes.error, ValueError):
                    logger.debug("Live-Status: Client getrennt oder Anfrage fehlgeschlagen", exc_info=True)
                finally:
                    try:
                        win32pipe.DisconnectNamedPipe(handle)
                    except pywintypes.error:
                        pass
        except Exception as exc:
            self.error = type(exc).__name__
            logger.exception("Live-Status-Kanal konnte nicht gestartet werden")
        finally:
            self.ready.set()
            if handle is not None:
                handle.Close()
