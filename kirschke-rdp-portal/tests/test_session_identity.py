"""One definition of the session identity rule, and a guard against new copies."""

import pathlib
import re

import pytest

from shared.enums import SessionState
from shared.session_identity import (
    ACTIVE_SESSION_STATE_VALUES,
    ACTIVE_SESSION_STATES,
    is_active_session,
    is_console_session,
    session_username,
)
from workstation_agent.session_control import ACTIVE_STATES
from workstation_agent.wts.monitor import WTSSessionInfo


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"full_username": "KIRSCHKE\\mustermann"}, "KIRSCHKE\\mustermann"),
        ({"domain": "KIRSCHKE", "username": "mustermann"}, "KIRSCHKE\\mustermann"),
        ({"username": "mustermann"}, "mustermann"),
        # A domain without a user name is an unowned session, not "KIRSCHKE\".
        ({"domain": "KIRSCHKE"}, ""),
        ({}, ""),
        ({"full_username": "", "domain": "NB12", "username": "tester"}, "NB12\\tester"),
        ({"full_username": None, "username": "tester"}, "tester"),
        ({"full_username": "AZUREAD\\user", "domain": "IGNORED"}, "AZUREAD\\user"),
    ],
)
def test_session_username_covers_every_reported_shape(session, expected) -> None:
    assert session_username(session) == expected


def test_session_username_matches_the_agent_property() -> None:
    """The portal's dict rule and WTSSessionInfo.full_username must agree."""
    for domain, username in [("KIRSCHKE", "mustermann"), (None, "mustermann"), ("KIRSCHKE", None)]:
        info = WTSSessionInfo(session_id=3, username=username, domain=domain)
        assert session_username({"domain": domain, "username": username}) == info.full_username


def test_the_agent_and_the_portal_share_one_active_state_rule() -> None:
    assert ACTIVE_STATES is ACTIVE_SESSION_STATES
    assert ACTIVE_SESSION_STATE_VALUES == {state.value for state in ACTIVE_SESSION_STATES}


@pytest.mark.parametrize(
    "state", ["connected", "disconnected", "reconnected", "logon"]
)
def test_active_states_are_recognised(state: str) -> None:
    assert is_active_session({"session_state": state}) is True


@pytest.mark.parametrize("state", ["logoff", "none", "", None, "listen", "idle"])
def test_inactive_states_are_rejected(state) -> None:
    assert is_active_session({"session_state": state}) is False


def test_active_states_are_real_enum_members() -> None:
    for state in ACTIVE_SESSION_STATES:
        assert isinstance(state, SessionState)


def test_no_module_rebuilds_the_identity_rule_inline() -> None:
    """Guard against the five inline copies coming back (report finding).

    Any module that needs the Windows name of a reported session must call
    shared.session_identity.session_username.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    canonical = root / "shared" / "session_identity.py"
    inline_identity = re.compile(r"""get\(\s*["']full_username["']\s*\)""")
    inline_states = re.compile(
        r"""["']connected["']\s*,\s*["']disconnected["']\s*,\s*["']reconnected["']"""
    )
    offenders: list[str] = []
    for source_root in ("portal_app", "workstation_agent", "shared"):
        for path in sorted((root / source_root).rglob("*.py")):
            if path == canonical:
                continue
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                if inline_identity.search(line) or inline_states.search(line):
                    offenders.append(f"{path.relative_to(root).as_posix()}:{number}")
    assert not offenders, (
        "use shared.session_identity instead of rebuilding the rule:\n" + "\n".join(offenders)
    )


# --- Konsole oder RDP --------------------------------------------------------
#
# Der gemeldete Fehler: Eine Person war aus München verbunden, das Portal
# schrieb "Konsole am Gerät" und verweigerte die Abmeldung mit der Begründung,
# es handle sich um eine lokale Sitzung. In Wahrheit war es eine getrennte
# RDP-Sitzung.
#
# Ursache: ``WTSClientProtocolType`` beschreibt den *gerade angehängten* Client.
# Trennt sich eine RDP-Sitzung, hängt keiner mehr daran und Windows meldet 0 --
# denselben Wert wie für die Konsole. Damit galt jede getrennte RDP-Sitzung als
# Konsolensitzung, also ausgerechnet der häufigste Fall.
#
# Die Werte unten sind an echten WinStations gemessen, nicht angenommen.


def test_a_disconnected_rdp_session_is_not_the_console() -> None:
    """Der Fall, der das Ganze ausgelöst hat."""
    getrennt = {
        "display_name": "RDP-Tcp#5",
        "protocol_type": 0,  # Kein Client mehr dran -- nicht "Konsole".
        "is_console_session": True,
        "session_state": SessionState.DISCONNECTED.value,
    }

    assert not is_console_session(getrennt)


def test_a_connected_rdp_session_is_not_the_console() -> None:
    verbunden = {"display_name": "RDP-Tcp#1", "protocol_type": 2}

    assert not is_console_session(verbunden)


def test_the_console_station_is_the_console() -> None:
    konsole = {"display_name": "Console", "protocol_type": 0, "is_console_session": True}

    assert is_console_session(konsole)


def test_the_station_name_beats_a_wrong_console_flag() -> None:
    """Der Name gehört zur Sitzung, das Protokoll nur zur Verbindung."""
    rdp = {"display_name": "RDP-Tcp", "protocol_type": 0, "is_console_session": True}

    assert not is_console_session(rdp)


def test_without_a_station_name_the_flag_decides() -> None:
    """Rückfallebene für einen Agenten, der keinen Namen liefert."""
    assert is_console_session({"protocol_type": 0, "is_console_session": True})
    assert not is_console_session({"protocol_type": 0, "is_console_session": False})


def test_in_doubt_it_is_not_the_console() -> None:
    """Der Agent prüft die Berechtigung selbst und weist sonst mit eigener
    Begründung ab -- eine falsche Vermutung kostet einen Versuch, kein Recht."""
    assert not is_console_session({})


def test_the_agent_property_agrees_with_the_shared_rule() -> None:
    """Zwei Kopien derselben Regel hatten beide denselben Fehler."""
    getrennt = WTSSessionInfo(
        session_id=5,
        username="RainerJouaux",
        domain="AzureAD",
        display_name="RDP-Tcp#5",
        protocol_type=0,
        is_console_session=True,
        session_state=SessionState.DISCONNECTED,
    )

    assert getrennt.is_rdp_session
    assert not is_console_session(getrennt.to_dict())


def test_a_session_without_a_user_is_never_an_rdp_session() -> None:
    """Die Dienste-Sitzung und der RDP-Lauscher gehören niemandem."""
    lauscher = WTSSessionInfo(session_id=65536, display_name="RDP-Tcp", protocol_type=0)

    assert not lauscher.is_rdp_session
