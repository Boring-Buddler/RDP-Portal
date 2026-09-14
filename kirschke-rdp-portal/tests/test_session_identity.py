"""One definition of the session identity rule, and a guard against new copies."""

import pathlib
import re

import pytest

from shared.enums import SessionState
from shared.session_identity import (
    ACTIVE_SESSION_STATE_VALUES,
    ACTIVE_SESSION_STATES,
    is_active_session,
    session_username,
)
from workstation_agent.session_control import ACTIVE_STATES
from workstation_agent.wts.monitor import WTSSessionInfo


@pytest.mark.parametrize(
    ("session", "expected"),
    [
        ({"full_username": "KIRSCHKE\\becker"}, "KIRSCHKE\\becker"),
        ({"domain": "KIRSCHKE", "username": "becker"}, "KIRSCHKE\\becker"),
        ({"username": "becker"}, "becker"),
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
    for domain, username in [("KIRSCHKE", "becker"), (None, "becker"), ("KIRSCHKE", None)]:
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
