"""Bring an already running RDP window back to the front.

The portal knows which mstsc processes it started, but not their windows.  Without
this, a machine you are already connected to could only answer "ein Fenster läuft
bereits" -- correct, and useless, because the window may be minimised behind
everything else.  Windows is asked for the top-level windows of those exact
process IDs, so nothing outside what the portal itself launched is ever touched.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Iterable
from ctypes import wintypes

logger = logging.getLogger(__name__)

SW_RESTORE = 9

user32 = ctypes.WinDLL("User32.dll", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL

#: GetWindow(hwnd, GW_OWNER) -- an owned window is a dialog, not the session window.
GW_OWNER = 4


def windows_of_processes(pids: Iterable[int]) -> list[int]:
    """Return visible top-level windows, including credential/error dialogs."""
    wanted = {int(pid) for pid in pids}
    if not wanted:
        return []
    found: list[int] = []

    def visit(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if (
            process_id.value in wanted
            and user32.IsWindowVisible(hwnd)
        ):
            found.append(int(hwnd))
        return True

    if not user32.EnumWindows(WNDENUMPROC(visit), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return found


def focus_windows(pids: Iterable[int]) -> bool:
    """Restore windows and report whether Windows accepted a foreground request."""
    raised = False
    try:
        windows = windows_of_processes(pids)
    except OSError:
        logger.debug("RDP-Fenstersuche fehlgeschlagen", exc_info=True)
        return False
    for hwnd in windows:
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            raised = bool(user32.SetForegroundWindow(hwnd)) or raised
        except OSError:
            logger.debug("Fenster %s konnte nicht in den Vordergrund geholt werden", hwnd)
    return raised


__all__ = ["focus_windows", "windows_of_processes"]
