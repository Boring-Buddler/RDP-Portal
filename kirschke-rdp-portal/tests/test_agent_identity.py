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


# --- Wer darf eine fremde Sitzung beenden ------------------------------------


def controller_command(**overrides):
    from datetime import UTC, datetime
    account = "AzureAD" + chr(92) + "tester"
    command = {
        "protocol": "LOGOFF/1",
        "request_id": "request-1234567890",
        "requested_at_utc": datetime.now(UTC).isoformat(),
        "session_id": 3,
        "username": account,
        "login_time": "2026-09-10T08:00:00+00:00",
        "requester_identity": account,
        "expected_agent_id": "A",
    }
    command.update(overrides)
    return command


def test_a_client_mismatch_names_both_sides(monkeypatch):
    """Ohne beide Namen war die Ablehnung nicht nachvollziehbar."""
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from shared.enums import SessionState
    from workstation_agent import session_control as agent_control
    from workstation_agent.wts.monitor import WTSSessionInfo

    info = WTSSessionInfo(
        session_id=3, username="tester", domain="AzureAD", display_name="RDP-Tcp#7",
        client_name="PC12", client_address="192.168.2.76", protocol_type=2,
        session_state=SessionState.CONNECTED,
        login_time=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
    )
    monitor = Mock()
    monitor.__enter__ = Mock(return_value=monitor)
    monitor.__exit__ = Mock(return_value=False)
    monitor.get_user_sessions.return_value = [info]
    monkeypatch.setattr(agent_control, "WTSMonitor", Mock(return_value=monitor))
    controller = agent_control.AgentSessionController("A")

    with pytest.raises(PermissionError) as error:
        controller.handle(controller_command(), "NB05", False)

    message = str(error.value)
    assert "Anfrage kam von: NB05" in message
    assert "PC12" in message and "192.168.2.76" in message
    assert "administrative Abmeldung" in message
    monitor.logoff_session.assert_not_called()


# --- Derselbe Rechner unter verschiedenen Schreibweisen -----------------------


def owner_check(session_client_name, session_client_address, requesting_computer, monkeypatch=None):
    """Fuehrt die Besitzpruefung des Agenten mit einer gebauten Sitzung aus."""
    from datetime import UTC, datetime
    from unittest.mock import Mock

    from shared.enums import SessionState
    from workstation_agent import session_control as agent_control
    from workstation_agent.wts.monitor import WTSSessionInfo

    info = WTSSessionInfo(
        session_id=3, username="tester", domain="AzureAD", display_name="RDP-Tcp#7",
        client_name=session_client_name, client_address=session_client_address,
        protocol_type=2, session_state=SessionState.CONNECTED,
        login_time=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
    )
    monitor = Mock()
    monitor.__enter__ = Mock(return_value=monitor)
    monitor.__exit__ = Mock(return_value=False)
    monitor.get_user_sessions.return_value = [info]
    if monkeypatch is not None:
        monkeypatch.setattr(agent_control, "WTSMonitor", Mock(return_value=monitor))
    controller = agent_control.AgentSessionController("A")
    controller.handle(controller_command(), requesting_computer, False)
    return monitor


def test_the_same_machine_over_ipv4_and_ipv6_is_recognised(monkeypatch):
    """Der Live-Fall: RDP kam ueber IPv6, die Agent-Anfrage ueber IPv4.

    Die Sitzung meldet Namen plus IPv6-Link-Local, Windows bezeugt fuer die
    SMB-Verbindung nur die IPv4-Adresse. Ohne Aufloesung wurde eine Abmeldung vom
    genau richtigen Rechner abgelehnt.
    """
    from workstation_agent import session_control as agent_control

    monkeypatch.setattr(
        agent_control, "_resolved_aliases",
        lambda value, timeout=2.0: agent_control._machine_aliases(value)
        | ({"192.168.2.76"} if str(value).lower().startswith("pc12") else set())
        | ({"pc12"} if str(value).startswith("192.168.2.76") else set()),
    )
    monitor = owner_check("PC12", "fe80::d379:46e6:ce9f:1b74", "192.168.2.76", monkeypatch)

    monitor.logoff_session.assert_called_once()


def test_a_plain_name_match_needs_no_resolution(monkeypatch):
    """Der Normalfall darf keine Namensaufloesung kosten."""
    from workstation_agent import session_control as agent_control

    def must_not_run(value, timeout=2.0):
        raise AssertionError("Auf dem schnellen Weg darf nicht aufgeloest werden")

    monkeypatch.setattr(agent_control, "_resolved_aliases", must_not_run)
    monitor = owner_check("PC12", "192.168.2.76", "PC12", monkeypatch)

    monitor.logoff_session.assert_called_once()


def test_a_genuinely_different_machine_is_still_refused(monkeypatch):
    from workstation_agent import session_control as agent_control

    monkeypatch.setattr(
        agent_control, "_resolved_aliases",
        lambda value, timeout=2.0: agent_control._machine_aliases(value),
    )

    with pytest.raises(PermissionError, match="Anfrage kam von: FREMD-PC"):
        owner_check("PC12", "192.168.2.76", "FREMD-PC", monkeypatch)


def test_a_failing_lookup_degrades_to_a_refusal_not_a_hang():
    """Ohne DNS muss die Pruefung zuegig ablehnen, nicht haengen bleiben."""
    import time

    from workstation_agent.session_control import _resolved_aliases

    started = time.monotonic()
    aliases = _resolved_aliases("host.invalid.example", timeout=0.2)

    assert time.monotonic() - started < 3
    assert "host.invalid.example" in aliases


def test_resolution_keeps_the_plain_aliases():
    from workstation_agent.session_control import _machine_aliases, _resolved_aliases

    assert _machine_aliases("PC12") <= _resolved_aliases("PC12", timeout=0.2)
    assert _resolved_aliases(None, timeout=0.2) == set()
    assert _resolved_aliases("", timeout=0.2) == set()
