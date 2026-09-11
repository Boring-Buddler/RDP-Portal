"""Shared defaults and path handling for the local agent status channel."""

import os
from pathlib import Path


def expand_directory(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value).strip())).expanduser()


def default_portal_directory() -> Path:
    return (Path(os.environ.get("USERPROFILE") or Path.home())
            / "Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG"
            / "IB Kirschke - Dokumente" / "90" / "_K.I. Strategie"
            / "Testprogramme" / "RDP-Portal")


def default_agent_directory() -> Path:
    return default_portal_directory() / "remote" / "agenten-status"


def resolve_agent_directory(storage: str | Path) -> Path:
    """Migrate the old root-folder setting without nesting status folders."""
    directory = expand_directory(storage)
    if directory.name.casefold() in {"agent-status", "agenten-status"}:
        return directory
    candidates = [directory / "remote" / "agenten-status",
                  directory / "agenten-status", directory / "agent-status"]
    return next((candidate for candidate in candidates if candidate.is_dir()), candidates[0])
