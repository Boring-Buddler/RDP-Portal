import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from deployment.agent_installer import (
    bundle_payload,
    normalize_status_directory,
    validate_workstation_id,
)
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator
from portal_app.services.local_store import LocalStore
from portal_app.ui.main_window import MainWindow
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from shared.login_accounts import validate_login_account


@pytest.fixture
def account_window(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "portal-state.json")
    ws = Workstation("PILOT-01", "Pilot", "target", username_hint="TARGET\\old",
                     login_accounts=["TARGET\\alice"], trust_unverified_server=True)
    store.save([ws], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    return window


def test_selected_account_reaches_rdp_file_and_survives_restart(account_window, tmp_path):
    window = account_window
    ws = window.workstations[0]
    window._select_login_account(ws, "TARGET\\alice")
    restored, _, _ = LocalStore(window.store.path).load([], MockUser.create_user())
    profile = restored[0].get_rdp_profile("DOMAIN\\default")
    assert profile.username_hint == "TARGET\\alice"
    path = RDPFileGenerator(str(tmp_path)).generate(profile)
    assert "username:s:TARGET\\alice" in Path(path).read_text(encoding="utf-8")
    shared_data = json.loads(window.store.path.read_text(encoding="utf-8"))
    assert "selected_login_account" not in shared_data["workstations"][0]
    assert shared_data["workstations"][0]["username_hint"] == "TARGET\\old"


def test_plus_entry_requests_add_without_changing_selection(qtbot):
    ws = Workstation("P1", "Pilot", "target", login_accounts=["target\\alice"], selected_login_account="target\\alice")
    selector = LoginAccountSelector(ws, MockUser.create_user())
    qtbot.addWidget(selector)
    with qtbot.waitSignal(selector.add_requested):
        selector._activated(selector.combo.count() - 1)
    assert selector.combo.currentData() == "target\\alice"


def test_add_account_persists_only_account_list(account_window, monkeypatch):
    window = account_window
    ws = window.workstations[0]
    ws.display_name = "Unsaved title"
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getText", lambda *a, **k: ("TARGET\\bob", True))
    window._add_login_account(ws)
    restored = LocalStore(window.store.path).load([], MockUser.create_user())[0][0]
    assert restored.login_accounts == ["TARGET\\alice", "TARGET\\bob"]
    assert restored.selected_login_account == "TARGET\\bob"
    assert restored.display_name == "Pilot"
    assert restored.rdp_access_users == []  # No AD membership changes implied.


def test_duplicate_account_is_selected_without_duplicate_entry(account_window, monkeypatch):
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getText", lambda *a, **k: ("target\\ALICE", True))
    account_window._add_login_account(account_window.workstations[0])
    ws = account_window.workstations[0]
    assert ws.login_accounts == ["TARGET\\alice"]
    assert ws.selected_login_account == "TARGET\\alice"


def test_cancel_add_leaves_inventory_unchanged(account_window, monkeypatch):
    before = account_window.store.path.read_bytes()
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getText", lambda *a, **k: ("unused", False))
    account_window._add_login_account(account_window.workstations[0])
    assert account_window.store.path.read_bytes() == before


def test_connect_uses_selected_account(account_window, monkeypatch):
    window = account_window
    ws = window.workstations[0]
    window._select_login_account(ws, "TARGET\\alice")
    launch = Mock(return_value=(True, "started"))
    monkeypatch.setattr("portal_app.rdp.launch_rdp_session", launch)
    monkeypatch.setattr("portal_app.rdp.has_active_rdp_session", lambda *a: False)
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.information", lambda *a: None)
    window.on_connect_requested(ws)
    assert launch.call_args.args[0].username_hint == "TARGET\\alice"


@pytest.mark.parametrize("value", ["", "a\nredirectdrives:i:1", "a\x00b", "a" * 257, "DOMAIN\\", "a/b"])
def test_invalid_account_names_are_rejected(value):
    with pytest.raises(ValueError):
        validate_login_account(value)


def test_setup_bundle_check_and_paths_with_spaces(tmp_path):
    root = tmp_path / "unpacked setup"
    payload = root / "payload"
    payload.mkdir(parents=True)
    (payload / "Kirschke-RDP-Agent.exe").write_bytes(b"test payload")
    assert bundle_payload(root) == payload


def test_setup_rejects_missing_payload(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle_payload(tmp_path)


@pytest.mark.parametrize("value", ["WS-004", "NB12KI", "host.name_2"])
def test_native_setup_accepts_safe_workstation_ids(value):
    assert validate_workstation_id(value) == value


@pytest.mark.parametrize("value", ["", "-bad", "bad name", "bad/arg", "äöü"])
def test_native_setup_rejects_unsafe_workstation_ids(value):
    with pytest.raises(ValueError):
        validate_workstation_id(value)


def test_native_setup_requires_absolute_status_path():
    with pytest.raises(ValueError):
        normalize_status_directory("status")


def test_setup_code_does_not_launch_powershell():
    source = Path(__file__).parents[1] / "deployment" / "agent_installer.py"
    assert "powershell.exe" not in source.read_text(encoding="utf-8").casefold()
