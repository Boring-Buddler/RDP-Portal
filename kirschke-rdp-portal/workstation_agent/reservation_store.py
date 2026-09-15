"""Reservations the agent keeps on behalf of its own machine.

Until now a reservation existed only in the portal that made it, plus in the
shared state file for portals that were configured to read one. A portal on
another PC without that share saw a machine as free while someone had booked it.

The agent is the one thing every portal already talks to, so it keeps the
reservations for **its own machine** and hands them back with every status
snapshot. A portal that changes a booking pushes the new list here; every other
portal picks it up on its next query.

What this deliberately is *not*
-------------------------------
It is not an authorization boundary. The named pipe is reached through the
shared ``PortalLeser`` account, which identifies the portal, never the person
(see the logoff path in :mod:`workstation_agent.session_control` for the same
limit). So the agent cannot verify that the person pushing a reservation is the
one named in ``reserved_by``. That is acceptable because a reservation grants no
Windows rights whatsoever -- it is a note among colleagues about who intends to
use a machine, and the portal says so in the booking dialog. Anyone who can
reach the pipe could already read every session on the machine.

Conflicts between portals are resolved as last-write-wins, per machine. Two
people editing the same machine's bookings in the same few seconds can therefore
lose one edit; with the handful of machines this serves, that is a fair trade
against the coordination a stronger rule would need.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from shared.agent_snapshot import validate_reservations
from shared.file_io import write_json_atomic

logger = logging.getLogger(__name__)

#: Name of the file next to the agent configuration.
STORE_FILENAME = "agent-reservations.json"

#: A damaged or hostile file must not be read without limit before the JSON
#: parser ever sees it. The snapshot list is capped at 64 records of bounded
#: field length, so anything past this cannot be a legitimate store.
MAX_STORE_BYTES = 256_000


def default_store_path() -> Path:
    """Where the store lives: beside the agent's own configuration file.

    ``AGENT_CONFIG_PATH`` is what the installed scheduled task passes, so the
    store follows the installation rather than the working directory of
    whichever process happens to start the agent.
    """
    configured = os.getenv("AGENT_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().parent / STORE_FILENAME
    data_root = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    return data_root / "KirschkeRDPAgent" / STORE_FILENAME


class ReservationStore:
    """The machine's reservation list, persisted across agent restarts.

    Guarded by a lock because the status pipe handler writes it while the
    snapshot builder reads it, and those run on different threads.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()
        self._lock = threading.Lock()
        self._reservations: list[dict[str, Any]] = []
        self._loaded = False

    def load(self) -> list[dict[str, Any]]:
        """Read the stored list once, tolerating every kind of damaged file.

        A store that cannot be read must never keep the agent from starting: the
        reservations are convenience information, while the status channel and
        the logoff path are what the machine is actually needed for.
        """
        with self._lock:
            if self._loaded:
                return list(self._reservations)
            self._loaded = True
            try:
                if self.path.stat().st_size > MAX_STORE_BYTES:
                    logger.warning("Reservierungsdatei zu groß, wird ignoriert: %s", self.path)
                    return []
                raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except FileNotFoundError:
                return []
            except (OSError, ValueError):
                logger.warning("Reservierungsdatei nicht lesbar: %s", self.path, exc_info=True)
                return []
            try:
                self._reservations = validate_reservations(
                    raw.get("reservations") if isinstance(raw, dict) else raw
                )
            except ValueError:
                logger.warning("Reservierungsdatei verworfen: unerwarteter Inhalt")
                self._reservations = []
            return list(self._reservations)

    def current(self) -> list[dict[str, Any]]:
        """The list to put into a snapshot."""
        self.load()
        with self._lock:
            return list(self._reservations)

    def replace(self, reservations: Any) -> list[dict[str, Any]]:
        """Accept a portal's new list for this machine and persist it.

        Raises ``ValueError`` for anything that does not look like a reservation
        list; the caller turns that into a refusal the portal can display.
        """
        checked = validate_reservations(reservations)
        with self._lock:
            self._loaded = True
            self._reservations = checked
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                write_json_atomic(self.path, {"reservations": checked})
            except OSError:
                # The list stays in memory and is still reported, it just will
                # not survive a restart. Refusing here would discard a booking
                # that every portal can otherwise see right away.
                logger.warning(
                    "Reservierungen konnten nicht gespeichert werden: %s", self.path, exc_info=True
                )
            return list(checked)

    def handle(self, command: dict, client_computer: str) -> dict:
        """Handle one ``RESERVE/1`` request from a portal."""
        if not isinstance(command, dict) or command.get("protocol") != "RESERVE/1":
            raise ValueError("Unerwartetes Reservierungsprotokoll.")
        stored = self.replace(command.get("reservations"))
        logger.info(
            "Reservierungen von %s übernommen: %d Eintrag/Einträge.",
            client_computer or "unbekannt",
            len(stored),
        )
        return {"ok": True, "count": len(stored)}


__all__ = ["MAX_STORE_BYTES", "STORE_FILENAME", "ReservationStore", "default_store_path"]
