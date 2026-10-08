"""Gemeinsam genutzte Konten wie RDPUser und die eigenen Konten in "Anmelden als".

Auf den Rechenmaschinen melden sich alle unter einem Konto an, damit im Notfall
jemand anderes an eine laufende Berechnung kommt. Wer RDPUser unter seinen
eigenen Konten führte, sah jede RDPUser-Sitzung als seine eigene -- auch die
eines Kollegen. Für ein als gemeinsam markiertes Konto zählt deshalb nur noch,
was Windows bezeugt: dass die Sitzung von diesem PC aus aufgebaut wurde.
"""

import pytest
from PySide6.QtCore import Qt

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services import local_identity
from portal_app.services.local_store import LocalStore
from portal_app.ui.machine_actions import MachineState, machine_state
from shared.enums import AgentStatus, SessionState
from shared.identity import SharedWindowsIdentity, is_entra_profile_name

BACKSLASH = chr(92)
SHARED = "." + BACKSLASH + "RDPUser"
HERE = "NB12KI"
COLLEAGUE = "NB05"
ENTRA_UPN = "becker@prof-kirschke.de"
ENTRA_LOGIN = "AzureAD" + BACKSLASH + ENTRA_UPN
PROFILE_NAME = "AzureAD" + BACKSLASH + "ChristianBecker"


@pytest.fixture(autouse=True)
def this_pc(monkeypatch):
    monkeypatch.setattr(local_identity, "_client_names_cache", None)
    monkeypatch.setattr(local_identity, "local_machine_names", lambda: {HERE.casefold(), "192.168.2.76"})


def session(client: str | None = COLLEAGUE, state: str = "connected", name: str = "PC07\\RDPUser"):
    domain, _, account = name.partition(BACKSLASH)
    return {
        "session_id": 2,
        "username": account,
        "domain": domain,
        "full_username": name,
        "session_state": state,
        "login_time": "2026-10-08T07:56:54+00:00",
        "is_console_session": False,
        "client_name": client,
        "client_address": None,
    }


def machine(*sessions) -> Workstation:
    ws = Workstation("WS-7", "PC07", "PC07", ip_address="192.168.20.210")
    ws.agent_status = AgentStatus.ONLINE
    ws.agent_status_source = "live"
    ws.current_session_state = SessionState.CONNECTED
    ws.agent_sessions = list(sessions)
    return ws


def user(*, shared: bool = True) -> MockUser:
    person = MockUser.create_user()
    person.own_accounts = [SHARED]
    person.shared_accounts = [SHARED] if shared else []
    return person


def test_a_colleague_on_the_shared_account_is_not_me():
    ws = machine(session(client=COLLEAGUE))

    assert ws.owned_sessions(user().windows_accounts(), ENTRA_UPN) == []
    assert machine_state(ws, user()) == MachineState.OCCUPIED_OTHER


def test_my_own_connection_on_the_shared_account_is_mine():
    ws = machine(session(client=HERE))

    assert len(ws.owned_sessions(user().windows_accounts(), ENTRA_UPN)) == 1
    assert machine_state(ws, user(), window_open=True) == MachineState.OCCUPIED_SELF


def test_the_client_address_counts_as_well():
    item = session(client=None)
    item["client_address"] = "192.168.2.76"

    assert len(machine(item).owned_sessions(user().windows_accounts())) == 1


def test_a_disconnected_shared_session_can_no_longer_be_attributed():
    """Ohne Client bezeugt Windows nichts mehr -- dann ist es nicht sicher meine."""
    ws = machine(session(client=None, state="disconnected"))

    assert machine_state(ws, user()) == MachineState.OCCUPIED_OTHER_IDLE


def test_an_unmarked_account_keeps_the_name_match():
    """Persönliche Konten verhalten sich wie bisher, auch von einem anderen PC aus."""
    ws = machine(session(client=COLLEAGUE))

    assert len(ws.owned_sessions(user(shared=False).windows_accounts())) == 1


def test_the_shared_account_carries_this_pcs_names():
    accounts = user().windows_accounts()
    shared = [item for item in accounts if isinstance(item, SharedWindowsIdentity)]

    assert len(shared) == 1
    assert HERE.casefold() in shared[0].clients


def test_the_mark_survives_saving_and_loading():
    person = user()
    data = LocalStore._user_data(person)
    loaded = LocalStore._user_from_data(data, MockUser.create_user())

    assert loaded.shared_accounts == [SHARED]
    assert loaded.is_shared_account(SHARED.upper())


def test_a_mark_without_its_account_is_dropped():
    data = LocalStore._user_data(user())
    data["own_accounts"] = []

    assert LocalStore._user_from_data(data, MockUser.create_user()).shared_accounts == []


def test_the_profile_name_is_recognised():
    assert is_entra_profile_name(PROFILE_NAME)
    assert not is_entra_profile_name(ENTRA_LOGIN)
    assert not is_entra_profile_name(ENTRA_UPN)
    assert not is_entra_profile_name(SHARED)


# --- "Anmelden als" ---------------------------------------------------------


def entries(selector) -> list[str]:
    return [selector.combo.itemText(row) for row in range(selector.combo.count())]


def selector_for(person: MockUser, qtbot):
    from portal_app.ui.widgets.login_account_selector import LoginAccountSelector

    widget = LoginAccountSelector(machine(), person)
    qtbot.addWidget(widget)
    return widget


def test_own_accounts_appear_for_every_machine(qtbot):
    person = user()
    person.rdp_username = None
    person.own_accounts = [SHARED, ENTRA_LOGIN, PROFILE_NAME, ENTRA_UPN]

    shown = entries(selector_for(person, qtbot))

    assert "Gemeinsam · " + SHARED in shown
    assert "Eigenes · " + ENTRA_LOGIN in shown
    # Dieselbe Person in der zweiten Schreibweise nicht noch einmal.
    assert not any(text.endswith(" " + ENTRA_UPN) for text in shown)
    # Mit dem Profilnamen lehnt Windows jede Anmeldung ab.
    assert not any(PROFILE_NAME in text for text in shown)


def test_the_default_account_is_not_listed_twice(qtbot):
    person = user()
    person.rdp_username = ENTRA_UPN
    person.rdp_domain = None
    person.own_accounts = [ENTRA_LOGIN]

    shown = entries(selector_for(person, qtbot))

    assert shown[0] == "Standard · " + ENTRA_UPN
    assert not any(ENTRA_LOGIN in text for text in shown)


def test_picking_an_own_account_selects_it(qtbot):
    person = user()
    person.rdp_username = None
    widget = selector_for(person, qtbot)
    picked = []
    widget.account_selected.connect(lambda ws, account: picked.append(account))

    index = widget.combo.findData(SHARED)
    widget.combo.setCurrentIndex(index)
    widget._activated(index)

    assert picked == [SHARED]


# --- Einstellungen ----------------------------------------------------------


def test_the_settings_dialog_stores_the_mark(qtbot):
    from portal_app.ui.widgets.user_settings_dialog import UserSettingsDialog

    person = user(shared=False)
    person.own_accounts = [SHARED, ENTRA_LOGIN]
    dialog = UserSettingsDialog(person)
    qtbot.addWidget(dialog)

    assert dialog.listed_shared_accounts() == []
    dialog.own_accounts.item(0).setCheckState(Qt.Checked)
    dialog._accept()

    assert person.own_accounts == [SHARED, ENTRA_LOGIN]
    assert person.shared_accounts == [SHARED]
