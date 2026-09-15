"""Das Portal lernt die Schreibweise, unter der der Agent die Sitzung meldet.

Beim Verbinden merkt sich das Portal das Konto, mit dem es verbindet. Bei einem
Entra-Konto ist das die UPN (``schaelike-adm@firma.de``), waehrend der Agent
dieselbe Sitzung unter dem Profilnamen meldet
(``AzureAD\\HendrikSchaelikeAdmin``). Die beiden lassen sich nicht auseinander
herleiten -- die eigene Maschine erschien deshalb weiter als fremd belegt.

Die Verbindung zwischen beiden Formen wird nicht geraten: Die Sitzung nennt
diesen Rechner als ihren RDP-Client, und das bezeugt Windows.
"""

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore
from portal_app.ui.machine_actions import MachineState, machine_state
from shared.enums import AgentStatus, SessionState

BACKSLASH = chr(92)
PROFILE_NAME = "AzureAD" + BACKSLASH + "HendrikSch" + chr(0xE4) + "likeAdmin"
UPN = "schaelike-adm@prof-kirschke.de"
HERE = "PC12"


def session(client=HERE, name=PROFILE_NAME, state="connected"):
    domain, _, account = name.partition(BACKSLASH)
    return {
        "session_id": 2,
        "username": account or domain,
        "domain": domain if account else "",
        "full_username": name,
        "session_state": state,
        "login_time": "2026-09-15T07:56:54+00:00",
        "is_console_session": False,
        "client_name": client,
        "client_address": "192.168.2.76",
        "sid": "S-1-12-1-26",
    }


def machine(*sessions):
    ws = Workstation("WS-2", "WORKSTATION", "PC07", ip_address="192.168.20.210")
    ws.agent_status = AgentStatus.ONLINE
    ws.agent_status_source = "live"
    ws.current_session_state = SessionState.CONNECTED
    ws.agent_sessions = list(sessions)
    return ws


@pytest.fixture
def window(tmp_path, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    user = MockUser.create_user()
    # Genau das, was der Verbindungsaufbau heute schon eintraegt -- und was allein
    # nicht reicht.
    user.own_accounts = [UPN]
    store = LocalStore(tmp_path / "state.json")
    store.save([machine()], user, [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    monkeypatch.setattr("portal_app.ui.main_window.detect_initial_user", lambda *a: user)
    widget = MainWindow(automatic_live_status=False)
    qtbot.addWidget(widget)
    monkeypatch.setattr(
        "portal_app.services.local_identity.local_machine_names",
        lambda: {HERE.casefold()},
    )
    return widget


def with_window_open(monkeypatch, open_for=("WS-2",)):
    monkeypatch.setattr(
        "portal_app.rdp.has_active_rdp_session", lambda key: key in open_for
    )


# --- Der Kern ----------------------------------------------------------------

def test_the_upn_alone_leaves_the_machine_looking_foreign(window):
    ws = machine(session())
    window.workstations[:] = [ws]

    assert machine_state(ws, window.current_user) == MachineState.OCCUPIED_OTHER


def test_the_reported_spelling_is_adopted(window, monkeypatch):
    with_window_open(monkeypatch)
    ws = machine(session())
    window.workstations[:] = [ws]

    assert window._learn_reported_account(ws) is True

    assert PROFILE_NAME in window.current_user.own_accounts
    # Die Maschine gilt jetzt als eigene. Orange oder blau entscheidet danach nur
    # noch, ob dieses Portal ein Fenster dafuer offen hat.
    assert machine_state(ws, window.current_user) == MachineState.OWN_IDLE
    assert (
        machine_state(ws, window.current_user, window_open=True)
        == MachineState.OCCUPIED_SELF
    )


def test_adopting_twice_changes_nothing(window, monkeypatch):
    with_window_open(monkeypatch)
    ws = machine(session())
    window.workstations[:] = [ws]
    window._learn_reported_account(ws)

    assert window._learn_reported_account(ws) is False


# --- Wann nicht ---------------------------------------------------------------

def test_nothing_is_adopted_without_an_open_window(window, monkeypatch):
    """Sonst wuerde eine Sitzung uebernommen, die jemand anderes von hier oeffnete."""
    with_window_open(monkeypatch, open_for=())
    ws = machine(session())

    assert window._learn_reported_account(ws) is False
    assert PROFILE_NAME not in window.current_user.own_accounts


def test_a_session_from_another_computer_is_not_adopted(window, monkeypatch):
    with_window_open(monkeypatch)
    ws = machine(session(client="EIN-ANDERER-PC"))
    ws.agent_sessions[0]["client_address"] = "10.0.0.9"

    assert window._learn_reported_account(ws) is False
    assert PROFILE_NAME not in window.current_user.own_accounts


def test_a_logged_off_session_is_not_adopted(window, monkeypatch):
    with_window_open(monkeypatch)
    ws = machine(session(state="logged_off"))

    assert window._learn_reported_account(ws) is False


def test_the_client_address_also_counts(window, monkeypatch):
    """Meldet der Agent keinen Namen, bleibt die Adresse als Nachweis."""
    monkeypatch.setattr(
        "portal_app.services.local_identity.local_machine_names",
        lambda: {"192.168.2.76"},
    )
    with_window_open(monkeypatch)
    ws = machine(session(client=""))

    assert window._learn_reported_account(ws) is True
    assert PROFILE_NAME in window.current_user.own_accounts
