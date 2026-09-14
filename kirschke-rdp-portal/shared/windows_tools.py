"""Absolute paths for the Windows tools the portal shells out to.

A bare executable name lets CreateProcess search the application directory and
the working directory before System32.  Resolving the name here means a
``whoami.exe`` or ``powershell.exe`` dropped next to the portal cannot take over
a diagnostic or authorization call.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_NAME = re.compile(r"[A-Za-z0-9_.-]+\.exe")


def system_root() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows"))


def system32_tool(name: str) -> str:
    """Return the absolute System32 path for ``name``.

    Raises:
        ValueError: the name is not a plain executable file name.
        FileNotFoundError: Windows does not provide the tool on this system.
    """
    if not _NAME.fullmatch(name):
        raise ValueError(f"Kein zulässiger Windows-Werkzeugname: {name}")
    tool = system_root() / "System32" / name
    if not tool.is_file():
        raise FileNotFoundError(f"Windows-Werkzeug nicht gefunden: {tool}")
    return str(tool)


def powershell() -> str:
    """Return the absolute path of Windows PowerShell 5.1."""
    shell = system_root() / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not shell.is_file():
        raise FileNotFoundError(f"Windows PowerShell nicht gefunden: {shell}")
    return str(shell)


__all__ = ["powershell", "system32_tool", "system_root"]
