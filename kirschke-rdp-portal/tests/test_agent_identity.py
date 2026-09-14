"""Eine Regel dafuer, ob ein Agent zu einer Maschine gehoert -- fuer beide Wege.

Status und Abmeldung haben das frueher unterschiedlich beantwortet: der Status
akzeptierte einen passenden Hostnamen, die Abmeldung verglich nur die Maschinen-ID.
Eine Maschine, deren Portal-ID vom Hostnamen abweicht -- der Normalfall, weil
Portal-IDs erzeugt und Hostnamen gewachsen sind -- zeigte damit einen gesunden
Livestatus und verweigerte danach jede Abmeldung.
"""

import pytest

from portal_app.models.workstation import Workstation
from portal_app.services.agent_identity import (
    machine_hostnames,
    match_agent,
    mismatch_message,
    name_values,
)


def check(expected_id, assigned, hostnames, reported_id, reported_host):
    return match_agent(
        expected_id=expected_id,
        assigned_explicitly=assigned,
        hostnames=hostnames,
        reported_id=reported_id,
        reported_hostname=reported_host,
    )


def test_a_matching_id_always_wins() -> None:
    assert check("NB05", True, set(), "nb05", "irgendwas")
    assert check("NB05", False, set(), "NB05", None)


def test_a_generated_portal_id_still_matches_via_the_hostname() -> None:
    """Der Fall aus dem Betrieb: Portal-ID WS-003, Agent nennt sich NB05."""
    match = check("WS-003", False, {"nb05"}, "NB05", "NB05")

    assert match
    assert "Hostname" in match.reason


def test_an_explicit_assignment_is_not_overruled_by_a_hostname() -> None:
    """Hat jemand die Zuordnung gesetzt, ist eine andere ID ein echter Widerspruch."""
    match = check("NB05", True, {"nb06"}, "NB06", "NB06")

    assert not match
    assert "zugeordnete" in match.reason


def test_neither_id_nor_hostname_is_a_refusal() -> None:
    match = check("WS-003", False, {"nb05"}, "NB06", "NB06")

    assert not match
    assert not match.matches


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("NB05", {"nb05"}),
        ("nb05.firma.local", {"nb05.firma.local", "nb05"}),
        ("NB05.", {"nb05"}),
        ("192.168.2.68", {"192.168.2.68"}),
        ("", set()),
        (None, set()),
    ],
)
def test_name_values_covers_the_spellings_of_one_host(value, expected) -> None:
    assert name_values(value) == expected


def test_machine_hostnames_uses_hostname_and_fqdn() -> None:
    workstation = Workstation("W1", "NB05", "NB05", fqdn="nb05.firma.local")

    assert machine_hostnames(workstation) == {"nb05", "nb05.firma.local"}


def test_a_machine_without_an_fqdn_does_not_gain_an_empty_name() -> None:
    assert machine_hostnames(Workstation("W1", "NB05", "NB05")) == {"nb05"}


def test_the_mismatch_message_names_both_sides_and_the_way_out() -> None:
    text = mismatch_message("NB05", "WS-003", "NB06", "NB06", "Testgrund")

    assert "WS-003" in text and "NB06" in text
    assert "Testgrund" in text
    assert "Agent zuordnen" in text
    # Die Frage, die sonst als Naechstes kommt, direkt beantwortet.
    assert "keine Rechtefrage" in text
