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


def resolve_portal_storage(value: str | Path) -> Path:
    """Recover a copied profile path only when this profile has actual portal data.

    Never create a guessed mirror of a shared library. Explicit reachable paths
    stay intact; a missing path can only migrate to an existing inventory.
    """
    directory = expand_directory(value)
    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    try:
        if directory.exists() or not directory.is_relative_to(profile.parent):
            return directory
        relative = directory.relative_to(profile.parent)
        if len(relative.parts) < 2 or relative.parts[0].casefold() == profile.name.casefold():
            return directory
        candidate = profile.joinpath(*relative.parts[1:])
        if (candidate / "portal-state.json").is_file():
            return candidate
    except OSError:
        pass
    return directory


def local_app_directory() -> Path:
    """The portal's own folder on this PC. Always present, never a network path."""
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
    return Path(local_data) / "KirschkeRDPPortal"


def is_private_program_location(directory: str | Path) -> bool:
    """Ob dieser Ordner im lokalen Profilbereich liegt und deshalb nie geteilt wird.

    Gebraucht, damit das Portal nicht das Falsche behauptet. Das Setup
    installiert nach ``%LOCALAPPDATA%\\Programs\\KirschkeRDPPortal``, und der
    gemeinsame Stand liegt neben der EXE -- also mitten im eigenen Profil.
    Die Anzeige versprach dort trotzdem eine "Verteilung nach
    SharePoint-Synchronisierung": Sie verglich gegen
    ``%LOCALAPPDATA%\\KirschkeRDPPortal`` und traf den Installationspfad damit
    nie. Wer dem Text folgte, wartete auf eine Synchronisierung, die es nicht
    gibt.

    Geprüft wird gegen die Profilordner selbst und nicht gegen einen einzelnen
    Programmordner darin: Wo die EXE unterhalb davon liegt, ist für diese Frage
    gleichgültig. OneDrive nimmt weder ``%LOCALAPPDATA%`` noch ``%APPDATA%``
    mit, ein synchronisierter Ordner liegt immer woanders.
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


def legacy_portal_directory() -> Path:
    """The SharePoint folder the portal used to default to.

    It is no longer assumed and never created. The path guessed at a
    synchronised document library, which is fine on the PC it was written for and
    wrong everywhere else: on a machine without that library the portal tried to
    create the chain and was refused partway up, and on a machine where the
    library existed but a folder inside it was not writable it was refused there.
    Creating it where it did not belong would have been worse still -- a
    look-alike that never syncs, with everyone believing they share a state that
    in truth exists once per machine.

    It stays here for one purpose: an installation that already keeps its state
    there must keep finding it. See ``LocalStore._configured_directory``.
    """
    return (Path(os.environ.get("USERPROFILE") or Path.home())
            / "Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG"
            / "IB Kirschke - Dokumente" / "90" / "_K.I. Strategie"
            / "Testprogramme" / "RDP-Portal")


def portal_program_directory() -> Path:
    """Use the EXE's location, never the working directory or PyInstaller temp."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def default_portal_directory() -> Path:
    """Portable shared inventory in state beside the portal executable."""
    return portal_program_directory() / "state"


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
