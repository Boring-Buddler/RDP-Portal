"""Shared defaults and path handling for the local agent status channel."""

import os
from pathlib import Path


def expand_directory(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value).strip())).expanduser()


def local_app_directory() -> Path:
    """The portal's own folder on this PC. Always present, never a network path."""
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
    return Path(local_data) / "KirschkeRDPPortal"


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


def default_portal_directory() -> Path:
    """Where the portal stores its state unless something else is configured.

    Local by default. A folder shared between portals is a deliberate setting in
    the admin area, not a guess about how somebody's OneDrive is laid out.
    """
    return local_app_directory() / "daten"


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
