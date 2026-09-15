"""Share reservations between portals through each machine's own agent.

A reservation used to live only in the portal that made it, plus in the shared
state file for portals configured to read one. A colleague's portal on another
PC therefore showed a machine as free while it was booked.

Every portal already talks to the agent of the machine it cares about, so the
agent carries the booking: the portal that changes a reservation pushes the new
list for that machine, and every other portal picks it up with the next status
query. See :mod:`workstation_agent.reservation_store` for what the agent does
with it, and why this is a note among colleagues rather than a right.
"""

from __future__ import annotations

import logging

from portal_app.models.reservation import Reservation
from portal_app.models.workstation import Workstation
from shared.status_pipe import push_agent_reservations

logger = logging.getLogger(__name__)


def reservations_for(workstation_id: str, reservations: list[Reservation]) -> list[dict]:
    """The records belonging to one machine, in the form the agent stores."""
    return [
        reservation.to_dict()
        for reservation in reservations
        if reservation.workstation_id == workstation_id
    ]


def affected_machines(
    before: list[Reservation],
    after: list[Reservation],
) -> set[str]:
    """Machines whose reservation list differs between two states.

    Only these need a push. A calendar edit usually touches one machine, and
    pushing to all of them would mean a pipe call per machine on every keystroke
    that reaches the store.
    """
    changed: set[str] = set()
    ids = {item.workstation_id for item in before} | {item.workstation_id for item in after}
    for workstation_id in ids:
        old = sorted(
            (item.to_dict() for item in before if item.workstation_id == workstation_id),
            key=lambda record: record["reservation_id"],
        )
        new = sorted(
            (item.to_dict() for item in after if item.workstation_id == workstation_id),
            key=lambda record: record["reservation_id"],
        )
        if old != new:
            changed.add(workstation_id)
    return changed


def push_for_machine(workstation: Workstation, reservations: list[Reservation]) -> str:
    """Send one machine's reservations to its agent.

    Returns an empty string on success, otherwise a message for the user. The
    caller must not treat a failure as a failed booking: the reservation is
    already saved locally, it just has not reached the other portals yet.
    """
    try:
        target = workstation.get_agent_status_target()
    except ValueError as exc:
        return f"{workstation.display_name}: kein Agentziel ({exc})"
    records = reservations_for(workstation.workstation_id, reservations)
    try:
        push_agent_reservations(target, records)
    except Exception as exc:  # noqa: BLE001 - jede Pipe-Störung ist hier gleichwertig
        logger.info(
            "Reservierungen für %s konnten nicht an den Agenten übergeben werden: %s",
            workstation.display_name,
            exc,
        )
        return f"{workstation.display_name}: {exc}"
    return ""


def merge_reported(
    reservations: list[Reservation],
    workstations: list[Workstation],
) -> tuple[list[Reservation], bool]:
    """Adopt what the agents reported, per machine.

    For a machine whose agent reported a list -- even an empty one -- that list
    is the truth, because the agent is the one place every portal writes to. A
    machine whose agent reported nothing (``None``: an agent older than 1.5.0,
    or one that was not reachable) keeps whatever this portal already had; the
    alternative would let one unreachable machine erase its bookings everywhere.
    """
    reported: dict[str, list[dict]] = {
        ws.workstation_id: ws.agent_reservations
        for ws in workstations
        if ws.agent_reservations is not None
    }
    if not reported:
        return reservations, False

    merged = [item for item in reservations if item.workstation_id not in reported]
    for workstation_id, records in reported.items():
        for record in records:
            try:
                merged.append(Reservation.from_dict(dict(record, workstation_id=workstation_id)))
            except (KeyError, TypeError, ValueError):
                # One damaged record must not cost the whole machine its list.
                logger.debug("Reservierung vom Agenten verworfen: %r", record, exc_info=True)

    before = sorted(item.to_dict()["reservation_id"] for item in reservations)
    after = sorted(item.to_dict()["reservation_id"] for item in merged)
    if before == after:
        # Same set of bookings: compare the contents too, so a moved time is
        # noticed while an unchanged list does not trigger a save.
        lookup = {item.reservation_id: item.to_dict() for item in reservations}
        if all(lookup.get(item.reservation_id) == item.to_dict() for item in merged):
            return reservations, False
    return merged, True


__all__ = [
    "affected_machines",
    "merge_reported",
    "push_for_machine",
    "reservations_for",
]
