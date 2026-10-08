"""Shared defaults and path handling for the local agent status channel."""

import os
import sys
from pathlib import Path


def expand_directory(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value).strip())).expanduser()


def portable_directory(value: str | Path) -> str:
    """Persist paths in this user's profile without embedding their account name."""
    directory = expand_directory(value)
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    if directory.is_absolute() and directory.is_relative_to(profile):
        return str(Path("%USERPROFILE%") / directory.relative_to(profile))
    return str(directory)


def is_network_location(value: str | Path) -> bool:
    """Ob ein Pfad auf einer Netzwerkfreigabe liegt: UNC oder verbundenes Laufwerk."""
    text = str(expand_directory(value))
    if text.startswith("\\\\"):
        return True
    drive = Path(text).drive
    if sys.platform != "win32" or not drive:
        return False
    import ctypes

    drive_remote = 4
    return int(ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")) == drive_remote


def local_app_directory() -> Path:
    """The portal's own folder on this PC. Always present, never a network path."""
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
    return Path(local_data) / "KirschkeRDPPortal"


def is_private_program_location(directory: str | Path) -> bool:
    """Ob dieser Ordner im lokalen Profilbereich liegt und deshalb nie geteilt wird.

    Gebraucht, damit das Portal nicht das Falsche behauptet. Das Setup
    installiert nach ``%LOCALAPPDATA%\\Programs\\KirschkeRDPPortal``, und der
    eigene Stand liegt neben der EXE -- also mitten im eigenen Profil.

    Geprüft wird gegen die Profilordner selbst und nicht gegen einen einzelnen
    Programmordner darin: Wo die EXE unterhalb davon liegt, ist für diese Frage
    gleichgültig. OneDrive nimmt weder ``%LOCALAPPDATA%`` noch ``%APPDATA%``
    mit.
    """
    try:
        target = expand_directory(directory).resolve()
    except OSError:
        return False
    for variable in ("LOCALAPPDATA", "APPDATA"):
        value = os.environ.get(variable)
        if not value:
            continue
        try:
            if target.is_relative_to(Path(value).resolve()):
                return True
        except (OSError, ValueError):
            continue
    return False


def portal_program_directory() -> Path:
    """Use the EXE's location, never the working directory or PyInstaller temp."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_portal_directory() -> Path:
    """Der eigene Stand: ``state`` neben der EXE, nie in einem Cloud-Ordner.

    Nach einer Installation per Setup liegt die EXE im lokalen Profil, und
    ``state`` daneben ist privat. Wird die portable EXE dagegen aus einem
    OneDrive- oder SharePoint-Ordner gestartet, landete der Stand -- samt
    Sperr-, Temporär- und Protokolldateien, die das Portal im Sekundentakt
    schreibt -- mitten in der Synchronisierung. Dann gilt der lokale Ordner.
    """
    from shared.sync_guard import is_synced_folder

    program = portal_program_directory()
    if is_synced_folder(program):
        return local_app_directory() / "daten"
    return program / "state"


def default_agent_directory() -> Path:
    return default_portal_directory() / "agenten-status"


def resolve_agent_directory(storage: str | Path) -> Path:
    """Migrate the old root-folder setting without nesting status folders."""
    directory = expand_directory(storage)
    if directory.name.casefold() in {"agent-status", "agenten-status"}:
        return directory
    candidates = [directory / "remote" / "agenten-status",
                  directory / "agenten-status", directory / "agent-status"]
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])
