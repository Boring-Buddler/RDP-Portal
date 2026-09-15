"""Reservierungen reisen ueber den Agenten der jeweiligen Maschine.

Vorher kannte eine Buchung nur das Portal, das sie angelegt hat (und, falls
eingerichtet, die gemeinsame Ablage). Ein Portal auf einem anderen PC zeigte die
Maschine als frei. Der Agent verwahrt die Liste jetzt fuer seine eigene Maschine
und gibt sie mit jedem Statusabruf zurueck.
"""

from datetime import datetime, timedelta

import pytest

from portal_app.models.reservation import Reservation
from portal_app.models.workstation import Workstation
from portal_app.services.reservation_sync import (
    affected_machines,
    merge_reported,
    push_for_machine,
    reservations_for,
)
from shared.agent_snapshot import AgentSnapshot, validate_reservations
from workstation_agent.reservation_store import ReservationStore

START = datetime(2026, 9, 20, 9, 0)


def booking(workstation_id="WS-1", identifier="r1", who="becker@prof-kirschke.de", hours=8):
    return Reservation(
        workstation_id=workstation_id,
        title="Statikberechnung",
        start=START,
        end=START + timedelta(hours=hours),
        reserved_by=who,
        reservation_id=identifier,
    )


def machine(identifier="WS-1", reported=None):
    ws = Workstation(identifier, identifier, identifier)
    ws.agent_reservations = reported
    return ws


# --- Was an welchen Agenten geht -------------------------------------------

def test_only_the_changed_machine_is_pushed():
    before = [booking("WS-1"), booking("WS-2", "r2")]
    after = [booking("WS-1"), booking("WS-2", "r2", hours=4)]

    assert affected_machines(before, after) == {"WS-2"}


def test_a_deleted_booking_still_counts_as_a_change():
    assert affected_machines([booking()], []) == {"WS-1"}


def test_an_unchanged_list_pushes_nothing():
    assert affected_machines([booking()], [booking()]) == set()


def test_only_that_machines_bookings_are_sent():
    records = reservations_for("WS-1", [booking("WS-1"), booking("WS-2", "r2")])

    assert [item["reservation_id"] for item in records] == ["r1"]


# --- Uebernahme dessen, was die Agenten melden -------------------------------

def test_a_reported_booking_reaches_this_portal():
    merged, changed = merge_reported([], [machine(reported=[booking().to_dict()])])

    assert changed is True
    assert [item.reservation_id for item in merged] == ["r1"]


def test_an_agent_that_reports_nothing_never_deletes_local_bookings():
    """None heisst "Agent aelter als 1.5.0 oder nicht erreichbar", nicht "keine"."""
    merged, changed = merge_reported([booking()], [machine(reported=None)])

    assert changed is False
    assert [item.reservation_id for item in merged] == ["r1"]


def test_an_empty_report_does_delete_them():
    """Eine leere Liste ist eine Aussage: der Agent fuehrt keine Buchung mehr."""
    merged, changed = merge_reported([booking()], [machine(reported=[])])

    assert changed is True
    assert merged == []


def test_an_unchanged_report_does_not_count_as_a_change():
    merged, changed = merge_reported([booking()], [machine(reported=[booking().to_dict()])])

    assert changed is False
    assert [item.reservation_id for item in merged] == ["r1"]


def test_a_damaged_record_does_not_cost_the_machine_its_list():
    reported = [booking().to_dict(), {"reservation_id": "kaputt"}]

    merged, changed = merge_reported([], [machine(reported=reported)])

    assert changed is True
    assert [item.reservation_id for item in merged] == ["r1"]


def test_other_machines_keep_their_bookings():
    merged, _ = merge_reported(
        [booking("WS-1"), booking("WS-2", "r2")],
        [machine("WS-1", reported=[])],
    )

    assert [item.reservation_id for item in merged] == ["r2"]


# --- Fehlerfall beim Senden --------------------------------------------------

def test_an_unreachable_agent_is_reported_and_not_raised(monkeypatch):
    monkeypatch.setattr(
        "portal_app.services.reservation_sync.push_agent_reservations",
        lambda *a, **k: (_ for _ in ()).throw(OSError("Pipe nicht erreichbar")),
    )

    message = push_for_machine(machine(), [booking()])

    assert "Pipe nicht erreichbar" in message


def test_a_machine_without_a_target_is_reported_too():
    ws = Workstation("WS-9", "WS-9", "")

    assert "WS-9" in push_for_machine(ws, [])


# --- Agentseitige Ablage -----------------------------------------------------

def test_the_agent_stores_and_returns_a_list(tmp_path):
    store = ReservationStore(tmp_path / "agent-reservations.json")

    store.handle({"protocol": "RESERVE/1", "reservations": [booking().to_dict()]}, "PORTAL-PC")

    assert [item["reservation_id"] for item in store.current()] == ["r1"]
    assert [item["reservation_id"] for item in ReservationStore(store.path).current()] == ["r1"]


def test_the_agent_refuses_a_foreign_protocol(tmp_path):
    store = ReservationStore(tmp_path / "agent-reservations.json")

    with pytest.raises(ValueError):
        store.handle({"protocol": "LOGOFF/1"}, "PORTAL-PC")


def test_a_damaged_store_leaves_the_agent_usable(tmp_path):
    path = tmp_path / "agent-reservations.json"
    path.write_text("{kaputt", encoding="utf-8")

    assert ReservationStore(path).current() == []


def test_the_store_refuses_an_implausible_flood(tmp_path):
    store = ReservationStore(tmp_path / "agent-reservations.json")
    flood = [dict(booking(identifier=f"r{index}").to_dict()) for index in range(200)]

    with pytest.raises(ValueError):
        store.replace(flood)


def test_a_record_with_a_missing_field_is_refused():
    with pytest.raises(ValueError):
        validate_reservations([{"reservation_id": "r1", "workstation_id": "WS-1"}])


# --- Snapshot-Format ---------------------------------------------------------

def test_an_old_agent_reports_no_reservations_key():
    snapshot = AgentSnapshot("WS-1", "host", "1.4.3")

    assert "reservations" not in snapshot.to_dict()
    assert AgentSnapshot.from_dict(snapshot.to_dict()).reservations is None


def test_an_empty_list_survives_the_round_trip():
    snapshot = AgentSnapshot("WS-1", "host", "1.5.0", reservations=[])

    assert AgentSnapshot.from_dict(snapshot.to_dict()).reservations == []
