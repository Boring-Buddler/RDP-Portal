"""Portable machine settings saved by one admin and read by another portal."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore, StoreReadError
from portal_app.ui.main_window import MainWindow
from shared.agent_paths import portal_program_directory


@pytest.fixture
def portals(tmp_path, monkeypatch, qtbot):
    first_store = LocalStore()
    first_store.save([Workstation("W1", "Workstation", "pc-01")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: first_store)
    first = MainWindow(automatic_live_status=False)
    qtbot.addWidget(first)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "second-profile"))
    second_store = LocalStore()
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: second_store)
    second = MainWindow(automatic_live_status=False)
    qtbot.addWidget(second)
    for window in (first, second):
        window.shared_store_sync_timer.stop()
        window._unlock_admin("Admin")
    return first, second


def test_admin_save_shares_all_machine_settings_but_not_personal_accounts(portals):
    first, second = portals
    ws = first.workstations[0]
    ws.display_name = "CAD-Arbeitsplatz"
    ws.hostname = "cad-01"
    ws.resolution = "2560x1440"
    ws.redirect_drives = True
    ws.login_accounts = ["DOMAIN\\cad"]
    ws.selected_login_account = "DOMAIN\\private"
    first.admin_view.save_button.click()
    second._sync_shared_store()
    received = second.workstations[0]
    assert (received.display_name, received.hostname, received.resolution) == (
        "CAD-Arbeitsplatz", "cad-01", "2560x1440"
    )
    assert received.redirect_drives
    assert received.login_accounts == ["DOMAIN\\cad"]
    assert received.selected_login_account is None
    assert "gespeichert" in first.admin_view.storage_status.text()
    assert first.store.preferences_path != second.store.preferences_path


def test_unsaved_machine_edits_survive_background_synchronization(portals):
    first, second = portals
    first.workstations[0].display_name = "Saved elsewhere"
    second.workstations[0].display_name = "My unsaved edit"
    first.admin_view.save_button.click()
    second._sync_shared_store()
    assert second.workstations[0].display_name == "My unsaved edit"


def test_concurrent_edit_is_reported_without_overwriting_shared_settings(portals, monkeypatch):
    first, second = portals
    first.workstations[0].display_name = "First edit"
    second.workstations[0].display_name = "Second edit"
    warning = Mock()
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.warning", warning)
    first.admin_view.save_button.click()
    second.admin_view.save_button.click()
    assert second._pending_save
    assert "NICHT gespeichert" in second.admin_view.storage_status.text()
    assert "Parallel" in warning.call_args.args[1]
    assert first.store._read_state(first.store.path)["workstations"][0]["display_name"] == "First edit"


def test_failed_save_can_be_retried(portals, monkeypatch):
    first, _ = portals
    first.workstations[0].description = "New settings"
    original = first.store.save
    monkeypatch.setattr(first.store, "save", Mock(side_effect=PermissionError("read only")))
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.warning", Mock())
    first.admin_view.save_button.click()
    assert first._pending_save
    assert first.admin_view.save_button.isEnabled()
    monkeypatch.setattr(first.store, "save", original)
    first.admin_view.save_button.click()
    assert not first._pending_save
    assert first.store._read_state(first.store.path)["workstations"][0]["description"] == "New settings"


def test_locked_admin_cannot_save(portals, monkeypatch):
    first, _ = portals
    first._lock_admin()
    saved = Mock()
    monkeypatch.setattr(first.store, "save", saved)
    first._save_admin_settings()
    assert not first.admin_view.save_button.isEnabled()
    saved.assert_not_called()


def test_executable_location_wins_over_working_directory_and_temp_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(tmp_path / "SharePoint" / "portal.exe"))
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path / "extracted"), raising=False)
    monkeypatch.chdir(tmp_path)
    assert portal_program_directory() == tmp_path / "SharePoint"


def test_legacy_machine_inventory_seeds_state_without_redirecting_or_deleting(tmp_path, monkeypatch):
    legacy = LocalStore(tmp_path / "old" / "portal-state.json")
    user = MockUser.create_user()
    legacy.save([Workstation("OLD", "Existing machine", "pc-old")], user, [])
    config = LocalStore._config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"storage_directory": str(legacy.directory)}), encoding="utf-8")
    store = LocalStore()
    machines, loaded_user, reservations = store.load([], user)
    assert machines[0].workstation_id == "OLD"
    assert store.directory == tmp_path / "portal" / "state"
    store.save(machines, loaded_user, reservations)
    assert legacy.path.exists()
    assert store.path.exists()
    # Once state exists, another profile's legacy inventory cannot replace it.
    legacy.save([Workstation("OTHER", "Other", "other")], user, [])
    assert LocalStore().load([], user)[0][0].workstation_id == "OLD"
    store.path.unlink()
    with pytest.raises(StoreReadError):
        store.load([], user)


def test_live_session_status_does_not_block_shared_refresh(portals):
    first, _ = portals
    first._saved_workstations = deepcopy(first.workstations)
    first.workstations[0].agent_version = "99.0.0"
    first.workstations[0].current_session_user = "DOMAIN\\live"
    assert not first._has_unsaved_machine_settings()


def test_first_start_recovers_local_fallback_when_old_share_is_missing(tmp_path):
    user = MockUser.create_user()
    fallback = LocalStore(LocalStore.local_directory() / "portal-state.json")
    fallback.save([Workstation("RECOVERED", "Local fallback", "pc-01")], user, [])
    config = LocalStore._config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"storage_directory": str(tmp_path / "missing-share")}), encoding="utf-8")
    store = LocalStore()
    assert store.load([], user)[0][0].workstation_id == "RECOVERED"
    assert store.directory == tmp_path / "portal" / "state"
