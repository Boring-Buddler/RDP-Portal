"""Fremde Sitzung ohne offenes Fenster, und der Weg, ein Konto als eigenes zu melden.

Ein geschlossenes RDP-Fenster beendet die Windows-Sitzung nicht, es trennt sie --
das Konto hält die Maschine, während niemand hinsieht. Für das eigene Konto
markiert das Portal das seit jeher orange; für eine fremde Person war es bisher
dasselbe Violett wie bei einer aktiv benutzten Maschine.

Gelesen wird das aus dem, was der Agent ohnehin meldet, statt aus einer Meldung
eines Portals an andere Portale: Der Agent sieht die Tatsache selbst, das deckt
auch eine Kollegin ab, die mit blankem mstsc verbunden ist, und es bleibt kein
Merker stehen, wenn jemandes Portal einfach verschwindet.
"""

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.ui.machine_actions import (
    MachineState,
    machine_state,
    state_is_dashed,
    state_secondary_color,
)
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from shared.enums import AgentStatus, SessionState

BACKSLASH = chr(92)
STRANGER = "AzureAD" + BACKSLASH + "HendrikSchaelikeAdmin"


def session(state="disconnected", name=STRANGER, sid="S-1-12-1-99", session_id=2):
    domain, _, user = name.partition(BACKSLASH)
    return {
        "session_id": session_id,
        "username": user or domain,
        "domain": domain if user else "",
        "full_username": name,
        "session_state": state,
        "login_time": "2026-09-15T07:56:54+00:00",
        "is_console_session": False,
        "sid": sid,
    }


def machine(*sessions, summary=SessionState.DISCONNECTED):
    ws = Workstation("WS-2", "PC07", "PC07")
    ws.agent_status = AgentStatus.ONLINE
    ws.agent_status_source = "live"
    ws.current_session_state = summary
    ws.agent_sessions = list(sessions)
    return ws


@pytest.fixture
def user():
    return MockUser.create_user()


# --- Zustand -----------------------------------------------------------------

def test_a_disconnected_foreign_session_gets_its_own_state(user):
    ws = machine(session("disconnected"))

    assert machine_state(ws, user) == MachineState.OCCUPIED_OTHER_IDLE


def test_a_connected_foreign_session_stays_violet(user):
    ws = machine(session("connected"), summary=SessionState.CONNECTED)

    assert machine_state(ws, user) == MachineState.OCCUPIED_OTHER


def test_one_connected_session_is_enough_to_stay_violet(user):
    """Sitzt noch jemand davor, ist die Maschine belegt -- egal wie viele ruhen."""
    ws = machine(
        session("disconnected", session_id=2),
        session("connected", name="AzureAD" + BACKSLASH + "Andere", sid="S-1-12-1-7", session_id=3),
        summary=SessionState.CONNECTED,
    )

    assert machine_state(ws, user) == MachineState.OCCUPIED_OTHER


def test_a_claimed_account_turns_the_machine_back_to_your_own(user):
    """Zugleich der Nachweis, dass der neue Zustand keine eigene Sitzung verschluckt."""
    ws = machine(session("disconnected", sid=None))
    ws.agent_sessions[0].pop("sid")
    assert machine_state(ws, user) == MachineState.OCCUPIED_OTHER_IDLE

    user.claim_account(STRANGER)

    assert machine_state(ws, user) == MachineState.OWN_IDLE


# --- Darstellung -------------------------------------------------------------

def test_exactly_the_two_idle_states_are_drawn_dashed():
    """Gestrichelt heißt überall: belegt, aber niemand verbunden."""
    dashed = {state for state in MachineState if state_is_dashed(state)}

    assert dashed == {MachineState.OWN_IDLE, MachineState.OCCUPIED_OTHER_IDLE}


def test_both_idle_states_share_the_same_second_dash():
    """Die Grundfarbe sagt wer, der orange Strich sagt "Fenster zu"."""
    from portal_app.ui.machine_actions import IDLE_DASH_COLOR, STATE_COLORS

    own = state_secondary_color(MachineState.OWN_IDLE)
    foreign = state_secondary_color(MachineState.OCCUPIED_OTHER_IDLE)

    assert own.rgb() == foreign.rgb() == IDLE_DASH_COLOR.rgb()
    # Die Grundfarben unterscheiden sich weiterhin: blau gegen violett.
    assert (
        STATE_COLORS[MachineState.OWN_IDLE].name()
        != STATE_COLORS[MachineState.OCCUPIED_OTHER_IDLE].name()
    )


def test_your_own_idle_session_keeps_the_full_border_width():
    """Betonung folgt weiter der Handlungsfaehigkeit, nicht der Strichart."""
    from portal_app.ui.machine_actions import STATE_EMPHASIS

    assert STATE_EMPHASIS[MachineState.OWN_IDLE].width == 4
    assert STATE_EMPHASIS[MachineState.OCCUPIED_OTHER_IDLE].width == 2


# --- "Das bin ich" (auf der Detailseite) -------------------------------------


def detail(ws, user, qtbot):
    widget = WorkstationDetailWidget(user)
    qtbot.addWidget(widget)
    widget.set_workstation(ws)
    return widget


def test_the_claim_row_offers_the_reported_account(qtbot, user):
    view = detail(machine(session("disconnected")), user, qtbot)

    assert view._claimable_account() == STRANGER
    assert STRANGER in view.claim_label.text()


def test_the_claim_button_reports_the_account(qtbot, user):
    view = detail(machine(session("disconnected")), user, qtbot)

    with qtbot.waitSignal(view.account_claim_requested) as blocker:
        view._on_claim()

    assert blocker.args[1] == STRANGER


def test_no_claim_is_offered_for_a_free_machine(qtbot, user):
    view = detail(machine(summary=SessionState.NONE), user, qtbot)

    assert view._claimable_account() == ""
    assert view.claim_btn.isVisible() is False


def test_no_claim_is_offered_when_two_strangers_are_signed_in(qtbot, user):
    """Welches Konto gemeint ist, wäre geraten -- und ein falscher Eintrag hält."""
    ws = machine(
        session("disconnected", session_id=2),
        session("disconnected", name="AzureAD" + BACKSLASH + "Andere", sid="S-1-12-1-7", session_id=3),
    )

    assert detail(ws, user, qtbot)._claimable_account() == ""


def test_a_claimed_account_removes_the_offer(qtbot, user):
    view = detail(machine(session("disconnected")), user, qtbot)
    user.claim_account(STRANGER)

    view.set_workstation(view.workstation)

    assert view._claimable_account() == ""
