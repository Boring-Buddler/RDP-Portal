"""Gemeinsame Daten nur über das Netzwerk, nie über OneDrive oder SharePoint.

Das Portal schreibt seinen Stand, Sperr- und Temporärdateien und das
Ereignisprotokoll im Sekundentakt. In einem synchronisierten Ordner führt das
zu Konfliktkopien und gesperrten Dateien. Diese Tests halten fest:

* Kein Ordner, den das Portal beschreibt, darf in OneDrive oder SharePoint
  liegen -- weder eingetragen noch als Standard.
* Das gemeinsame Inventar liegt auf einer Netzwerkfreigabe, und mehrere Portale
  schreiben dort nie gegeneinander.
* Ist die Freigabe weg, legt das Portal dort nichts an.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import (
    LocalStore,
    StoreConflictError,
    StoreReadError,
)
from shared import file_io, sync_guard
from shared.agent_paths import default_portal_directory, local_app_directory


@pytest.fixture(autouse=True)
def no_real_sync_roots(monkeypatch):
    """Die echte Registry und die echten OneDrive-Variablen dieses PCs aussperren."""
    for variable in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(sync_guard, "_registry_roots", lambda: iter(()))
    monkeypatch.setattr(sync_guard, "_file_attributes", lambda path: None)


@pytest.fixture
def network(monkeypatch):
    """tmp_path-Ordner gelten in diesen Tests als Netzwerkfreigabe."""
    monkeypatch.setattr("portal_app.services.local_store.is_network_location", lambda path: True)


def machine(workstation_id: str, name: str | None = None) -> Workstation:
    return Workstation(workstation_id, name or workstation_id, workstation_id.casefold())


# --- Erkennung synchronisierter Ordner ---------------------------------------


def test_a_plain_folder_is_not_synced(tmp_path):
    assert sync_guard.synced_folder_reason(tmp_path / "daten") is None


def test_the_onedrive_variable_marks_its_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDriveCommercial", str(tmp_path / "Wolke"))
    reason = sync_guard.synced_folder_reason(tmp_path / "Wolke" / "RDP-Portal")
    assert reason and "OneDriveCommercial" in reason
    assert sync_guard.synced_folder_reason(tmp_path / "Wolkenkratzer") is None


def test_a_synced_sharepoint_library_is_recognised_from_the_registry(tmp_path, monkeypatch):
    library = tmp_path / "Kirschke GmbH" / "IB Kirschke - Dokumente"
    monkeypatch.setattr(
        sync_guard, "_registry_roots", lambda: iter([(str(library), "SharePoint-Bibliothek (Kirschke)")])
    )
    reason = sync_guard.synced_folder_reason(library / "90" / "RDP-Portal")
    assert reason and "SharePoint-Bibliothek" in reason


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\x\OneDrive\RDP-Portal",
        r"C:\Users\x\OneDrive - Kirschke\RDP-Portal",
        r"\\kirschke.sharepoint.com@SSL\DavWWWRoot\sites\it\Dokumente",
        "https://kirschke.sharepoint.com/sites/it",
    ],
)
def test_onedrive_names_and_sharepoint_paths_are_refused(path):
    assert sync_guard.is_synced_folder(path)


def test_a_folder_named_like_onedrive_only_in_part_is_fine():
    assert not sync_guard.is_synced_folder(r"\\server\OneDriveBackup\RDP-Portal")


def test_cloud_file_attributes_mark_a_folder_without_any_registry_entry(tmp_path, monkeypatch):
    cloud = tmp_path / "irgendwo"
    cloud.mkdir()
    monkeypatch.setattr(
        sync_guard,
        "_file_attributes",
        lambda path: sync_guard.FILE_ATTRIBUTE_PINNED if Path(path) == cloud else 0x10,
    )
    assert sync_guard.is_synced_folder(cloud / "RDP-Portal")


def test_the_refusal_names_the_way_out(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path / "OD"))
    with pytest.raises(sync_guard.SyncedFolderError, match="Netzwerkfreigabe"):
        sync_guard.ensure_not_synced(tmp_path / "OD" / "x", "Das gemeinsame Inventar")


# --- Kein beschriebener Ordner in OneDrive -----------------------------------


def test_a_portable_exe_in_onedrive_keeps_its_state_local(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDrive", str(tmp_path / "portal"))
    assert default_portal_directory() == local_app_directory() / "daten"
    assert LocalStore().directory == local_app_directory() / "daten"


def test_a_portable_exe_elsewhere_keeps_state_beside_it(tmp_path):
    assert default_portal_directory() == tmp_path / "portal" / "state"


@pytest.mark.parametrize(
    "setter",
    [
        lambda store, path: store.set_event_log_directory(path),
        lambda store, path: store.set_agent_status_directory(path),
        lambda store, path: store.set_workstation_agent_status_directory("WS-1", path),
        lambda store, path: store.use_shared_inventory(path),
    ],
)
def test_no_folder_setting_accepts_onedrive(tmp_path, monkeypatch, network, setter):
    monkeypatch.setenv("OneDrive", str(tmp_path / "OD"))
    store = LocalStore()
    with pytest.raises(sync_guard.SyncedFolderError):
        setter(store, tmp_path / "OD" / "RDP")
    assert "OD" not in store.config_path.read_text(encoding="utf-8") if store.config_path.exists() else True


def test_an_old_onedrive_event_log_setting_is_ignored_and_reported(tmp_path, monkeypatch):
    store = LocalStore()
    store.config_path.parent.mkdir(parents=True, exist_ok=True)
    onedrive = tmp_path / "OD" / "Protokoll"
    store.config_path.write_text(json.dumps({"event_log_directory": str(onedrive)}), encoding="utf-8")
    monkeypatch.setenv("OneDrive", str(tmp_path / "OD"))

    assert store.event_log_directory is None
    assert store.events_path.parent == store.directory
    assert "OneDrive" in store.configuration_notice


def test_an_old_onedrive_inventory_setting_is_ignored(tmp_path, monkeypatch):
    config = LocalStore._config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(json.dumps({"inventory_directory": str(tmp_path / "OD" / "Inv")}), encoding="utf-8")
    monkeypatch.setenv("OneDrive", str(tmp_path / "OD"))

    store = LocalStore()

    assert store.directory == tmp_path / "portal" / "state"
    assert store.configuration_notice


# --- Gemeinsames Inventar auf der Freigabe -----------------------------------


def test_the_shared_inventory_must_be_on_the_network(tmp_path):
    store = LocalStore()
    with pytest.raises(ValueError, match="Netzwerkfreigabe"):
        store.use_shared_inventory(tmp_path / "lokal-statt-netz")


def test_setting_up_copies_the_own_state_to_an_empty_share(tmp_path, network):
    store = LocalStore()
    user = MockUser.create_user()
    store.save([machine("W1")], user, [])
    share = tmp_path / "freigabe"

    adopted = store.use_shared_inventory(share)

    assert adopted is False
    assert store.path == share / "portal-state.json"
    assert store.load([], user)[0][0].workstation_id == "W1"
    assert LocalStore().directory == share, "die Einstellung überlebt keinen Neustart"


def test_setting_up_adopts_an_existing_share_and_keeps_the_own_state(tmp_path, network):
    share = tmp_path / "freigabe"
    user = MockUser.create_user()
    first = LocalStore()
    first.save([machine("GEMEINSAM")], user, [])
    first.use_shared_inventory(share)

    os.environ["LOCALAPPDATA"] = str(tmp_path / "zweiter-pc")
    second = LocalStore(tmp_path / "zweiter" / "portal-state.json")
    second.save([machine("EIGEN")], user, [])
    own_before = second.path.read_bytes()

    assert second.use_shared_inventory(share) is True
    assert [ws.workstation_id for ws in second.load([], user)[0]] == ["GEMEINSAM"]
    assert (tmp_path / "zweiter" / "portal-state.json").read_bytes() == own_before


@pytest.fixture
def two_portals(tmp_path, network):
    share = tmp_path / "freigabe"
    user = MockUser.create_user()
    first = LocalStore(tmp_path / "pc1" / "portal-state.json")
    first.save([machine("W1"), machine("W2")], user, [])
    first.use_shared_inventory(share)
    second = LocalStore(tmp_path / "pc2" / "portal-state.json")
    second.use_shared_inventory(share)
    return first, second, user


def test_two_portals_editing_different_machines_both_keep_their_edit(two_portals):
    first, second, user = two_portals
    machines_1, _, reservations_1 = first.load([], user)
    machines_2, _, reservations_2 = second.load([], user)
    machines_1[0].display_name = "Von PC1"
    machines_2[1].display_name = "Von PC2"

    first.save(machines_1, user, reservations_1)
    second.save(machines_2, user, reservations_2)

    names = {ws.workstation_id: ws.display_name for ws in first.load([], user)[0]}
    assert names == {"W1": "Von PC1", "W2": "Von PC2"}


def test_two_portals_editing_the_same_machine_never_overwrite_each_other(two_portals):
    first, second, user = two_portals
    machines_1, _, reservations_1 = first.load([], user)
    machines_2, _, reservations_2 = second.load([], user)
    machines_1[0].display_name = "Fassung PC1"
    machines_2[0].display_name = "Fassung PC2"

    first.save(machines_1, user, reservations_1)
    with pytest.raises(StoreConflictError):
        second.save(machines_2, user, reservations_2)

    assert first.load([], user)[0][0].display_name == "Fassung PC1"


def test_the_account_list_is_merged_under_the_lock(two_portals):
    first, second, _ = two_portals
    first.save_directory_accounts(["KIRSCHKE\\a"])
    second.save_directory_accounts(["KIRSCHKE\\b"])
    assert first.load_directory_accounts() == ["KIRSCHKE\\a", "KIRSCHKE\\b"]


def test_a_missing_share_is_never_replaced_by_an_empty_inventory(two_portals):
    first, _, user = two_portals
    first.path.unlink()
    with pytest.raises(StoreReadError, match="fehlt"):
        first.load([], user)
    assert not first.path.exists()


def test_leaving_the_shared_inventory_keeps_the_machines(tmp_path, two_portals):
    first, _, user = two_portals
    share_state = first.path.read_bytes()
    local = first.use_local_inventory()

    assert [ws.workstation_id for ws in first.load([], user)[0]] == ["W1", "W2"]
    assert local == first.directory
    assert (tmp_path / "freigabe" / "portal-state.json").read_bytes() == share_state


# --- Ohne erreichbare Freigabe -----------------------------------------------


def test_without_the_share_the_portal_starts_from_its_last_copy(tmp_path, network, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    share = tmp_path / "freigabe"
    user = MockUser.create_user()
    seed = LocalStore()
    seed.save([machine("W1")], user, [])
    seed.use_shared_inventory(share)
    seed.load([], user)  # legt die lokale Kopie an
    share.rename(tmp_path / "freigabe-weg")

    store = LocalStore()
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.warning", Mock())
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)

    assert [ws.workstation_id for ws in window.workstations] == ["W1"]
    assert "NICHT" in window._storage_fallback_notice
    assert store.path.is_relative_to(local_app_directory())
    assert not share.exists(), "die Freigabe wurde angefasst"
    assert "NOTBETRIEB" in window.admin_view.storage_status.text()


# --- Schreiben auf der Freigabe ----------------------------------------------


def test_replacing_waits_for_a_reader_that_holds_the_file(tmp_path, monkeypatch):
    real_replace = os.replace
    attempts: list[int] = []

    def busy_twice(source, target):
        attempts.append(1)
        if len(attempts) <= 2:
            raise PermissionError(32, "Datei wird von einem anderen Prozess verwendet")
        real_replace(source, target)

    monkeypatch.setattr(file_io.os, "replace", busy_twice)
    file_io.write_json_atomic(tmp_path / "x.json", {"ok": True})

    assert json.loads((tmp_path / "x.json").read_text(encoding="utf-8")) == {"ok": True}
    assert len(attempts) == 3
    assert not list(tmp_path.glob(".x.json.*.tmp"))


def test_the_background_check_never_reads_the_share_on_the_ui_thread(tmp_path, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    store = LocalStore(tmp_path / "inventar" / "portal-state.json")
    store.save([machine("W1")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "portal_app.ui.main_window.file_signatures",
        Mock(side_effect=AssertionError("stat im UI-Thread")),
    )
    requested: list[object] = []
    monkeypatch.setattr(window.store_probe, "request", lambda paths: requested.append(paths) or True)

    window._sync_shared_store(blocking=False)

    assert requested == [store.change_probe_paths()]


def test_a_background_result_triggers_the_reload(tmp_path, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    store = LocalStore(tmp_path / "inventar" / "portal-state.json")
    store.save([machine("W1")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    other = LocalStore(store.path)
    other.load([], MockUser.create_user())
    other.save([machine("W1"), machine("W2")], MockUser.create_user(), [])

    with qtbot.waitSignal(window.store_probe.completed, timeout=5000):
        window._sync_shared_store(blocking=False)

    assert [ws.workstation_id for ws in window.workstations] == ["W1", "W2"]
    window.store_probe.stop()
