"""Isolated native WTS call used by the portal's background worker."""

from __future__ import annotations

import argparse


def request_logoff(target: str, session_id: int) -> None:
    """Ask Windows to log off one remote session and wait for completion."""
    import win32ts

    handle = win32ts.WTSOpenServer(target)
    try:
        win32ts.WTSLogoffSession(handle, session_id, True)
    finally:
        # WTSOpenServer returns PyWin32's self-owning PyTS_HANDLE. Calling the
        # module-level WTSCloseServer leaves that wrapper marked as open, so its
        # destructor closes the native handle a second time and may terminate
        # the helper with STATUS_HEAP_CORRUPTION (0xC0000374).  Close through
        # the wrapper so PyWin32 also clears its stored handle value.
        handle.Close()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("target")
    parser.add_argument("session_id", type=int)
    values = parser.parse_args(arguments)
    if not values.target or values.session_id <= 0:
        return 87  # ERROR_INVALID_PARAMETER
    try:
        request_logoff(values.target, values.session_id)
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code is None and exc.args and isinstance(exc.args[0], int):
            code = exc.args[0]
        return int(code) if isinstance(code, int) and 0 < code < 2**31 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
