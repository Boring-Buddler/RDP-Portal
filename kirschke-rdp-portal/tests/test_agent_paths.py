import json
from pathlib import Path

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.ui.main_window import MainWindow
from shared.agent_paths import default_agent_directory, expand_directory, resolve_agent_directory
from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot
from shared.enums import AgentStatus
from shared.enums import SessionState
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def test_userprofile_default_matches_requested_sharepoint_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    expected = tmp_path / "Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG" / "IB Kirschke - Dokumente" / "90" / "_K.I. Strategie" / "Testprogramme" / "RDP-Portal" / "remote" / "agenten-status"
    assert default_agent_directory() == expected
    assert expand_directory("%userprofile%/status") == tmp_path / "status"


def test_status_folder_is_used_directly_without_extra_child(tmp_path):
    for name in ("agent-status", "agenten-status"):
        directory = tmp_path / "remote" / name
        assert resolve_agent_directory(directory) == directory


def test_existing_legacy_status_folder_is_discovered(tmp_path):
    (tmp_path / "agent-status").mkdir()
    assert resolve_agent_directory(tmp_path) == tmp_path / "agent-status"


def test_new_default_preferred_when_both_status_folders_exist(tmp_path):
    (tmp_path / "agent-status").mkdir()
    preferred = tmp_path / "remote" / "agenten-status"
    preferred.mkdir(parents=True)
    assert resolve_agent_directory(tmp_path) == preferred


def test_explicit_agent_folder_survives_restart_and_storage_save(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profile"))
    store = LocalStore()
    target = tmp_path / "custom status"
    store.set_agent_status_directory(target)
    store._save_directory_config(tmp_path / "inventory")
    restored = LocalStore()
    assert restored.directory == tmp_path / "inventory"
    assert restored.agent_status_directory == target


def test_portal_reads_selected_status_folder_despite_stale_environment(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "inventory" / "portal-state.json")
    store.save([Workstation("PILOT", "Pilot", "target")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    monkeypatch.setenv("AGENT_STATUS_DIR", str(tmp_path / "wrong-old-folder"))
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    directory = tmp_path / "remote" / "agenten-status"
    write_agent_snapshot(AgentSnapshot("PILOT", "target", "1"), directory)
    window._change_agent_directory(str(directory))
    assert window.workstations[0].agent_status == AgentStatus.ONLINE
    assert window.agent_status_service.directory == directory
    assert LocalStore(store.path).agent_status_directory == directory
    assert "1 Maschine" in window.settings_view.agent_status.text()


def test_existing_inventory_inside_status_folder_still_loads_status(tmp_path, monkeypatch, qtbot):
    directory = tmp_path / "agenten-status"
    store = LocalStore(directory / "portal-state.json")
    store.save([Workstation("PILOT", "Pilot", "target")], MockUser.create_user(), [])
    write_agent_snapshot(AgentSnapshot("PILOT", "target", "1"), directory)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    assert window.workstations[0].agent_status == AgentStatus.ONLINE


def test_invalid_status_file_produces_diagnostic_instead_of_silent_skip(tmp_path):
    (tmp_path / "PILOT.json").write_text(json.dumps({"hostname": "target"}), encoding="utf-8")
    service = LocalAgentStatusService(directory=tmp_path)
    service.apply([Workstation("PILOT", "Pilot", "target")])
    assert service.last_snapshot_count == 0
    assert "PILOT.json" in service.last_errors[0]
    assert "workstation_id" in service.last_errors[0]


def test_status_writer_expands_profile_in_explicit_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    path = write_agent_snapshot(AgentSnapshot("PILOT", "target", "1"), Path("%userprofile%/agenten-status"))
    assert path == tmp_path / "agenten-status" / "PILOT.json"


def test_utf16_powershell_json_is_read_and_reported(tmp_path):
    snapshot = AgentSnapshot("PILOT", "target", "1")
    (tmp_path / "PILOT.json").write_text(json.dumps(snapshot.to_dict()), encoding="utf-16")
    service = LocalAgentStatusService(directory=tmp_path)
    ws = Workstation("PILOT", "Pilot", "target")
    service.apply([ws])
    assert ws.agent_status == AgentStatus.ONLINE
    assert "PILOT.json" in service.last_report
    assert service.last_file_count == service.last_snapshot_count == service.last_match_count == 1


def test_unreadable_directory_is_visible_as_error(tmp_path):
    service = LocalAgentStatusService(directory=tmp_path)
    with patch.object(Path, "iterdir", side_effect=PermissionError("ACCESS DENIED")):
        service.apply([Workstation("PILOT", "Pilot", "target")])
    assert "ACCESS DENIED" in service.last_report
    assert service.last_errors


def test_mismatched_and_stale_files_explain_actual_cause(tmp_path):
    write_agent_snapshot(AgentSnapshot("OTHER", "other", "1"), tmp_path)
    service = LocalAgentStatusService(directory=tmp_path)
    ws = Workstation("PILOT", "Pilot", "target")
    service.apply([ws])
    assert "passen nicht" in ws.agent_diagnostic
    assert "OTHER.json" in service.last_report
    assert service.last_file_count == 1 and service.last_match_count == 0
    write_agent_snapshot(AgentSnapshot("PILOT", "target", "1", observed_at_utc=datetime.now(timezone.utc) - timedelta(minutes=10)), tmp_path)
    service.apply([ws])
    assert ws.agent_status == AgentStatus.OFFLINE
    assert service.last_match_count == 1
    assert "Synchronisierung" in ws.agent_diagnostic


def test_host_alias_cannot_apply_one_snapshot_to_two_machines(tmp_path):
    write_agent_snapshot(AgentSnapshot("WRONG-ID", "target.example", "1"), tmp_path)
    service = LocalAgentStatusService(directory=tmp_path)
    machines = [Workstation("A", "A", "target"), Workstation("B", "B", "target.example")]
    service.apply(machines)
    assert service.last_match_count == 0
    assert all("nicht eindeutig" in ws.agent_diagnostic for ws in machines)


def test_different_ip_addresses_do_not_match_as_short_hostnames(tmp_path):
    write_agent_snapshot(AgentSnapshot("OTHER", "192.168.1.10", "1"), tmp_path)
    service = LocalAgentStatusService(directory=tmp_path)
    ws = Workstation("PILOT", "Pilot", "192.168.1.20")
    service.apply([ws])
    assert ws.agent_status == AgentStatus.OFFLINE
    assert service.last_match_count == 0
    ws.hostname = "192.168.1.10"
    service.apply([ws])
    assert ws.agent_status == AgentStatus.ONLINE


def test_new_json_updates_dashboard_details_report_and_restart(tmp_path, monkeypatch, qtbot):
    from PySide6.QtWidgets import QApplication, QLabel
    from portal_app.ui.widgets.workstation_cards import WorkstationCard

    store = LocalStore(tmp_path / "portal-state.json")
    store.save([Workstation("PILOT", "Pilot", "target")], MockUser.create_user(), [])
    directory = tmp_path / "agenten-status"
    directory.mkdir()
    store.set_agent_status_directory(directory)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    window.on_workstation_selected(window.workstations[0])
    write_agent_snapshot(AgentSnapshot("PILOT", "target", "1", current_session_state=SessionState.CONNECTED, current_session_user="TARGET\\tester"), directory)
    window._poll_agent_status()
    assert "1/1" in window.overview_view.agent_channel_status.text()
    assert "1 online" in window.summary.text()
    card = next(card for card in window.overview_view._cards
                if isinstance(card, WorkstationCard) and card.workstation is window.workstations[0])
    assert "Online" in card.findChild(QLabel, "cardStatus").text()
    assert any("TARGET\\tester" in label.text() for label in card.findChildren(QLabel))
    assert window.detail_view.value_labels["session_user"].text() == "TARGET\\tester"
    assert "PILOT.json" in window.settings_view.agent_report.toPlainText()
    window.settings_view.copy_agent_report.click()
    assert "TARGET\\tester" in QApplication.clipboard().text()
    window.overview_view.agent_diagnostics_button.click()
    assert window.stack.currentWidget() is window.settings_view
    window.on_refresh()
    assert window.detail_view.workstation is window.workstations[0]
    restarted = MainWindow(automatic_live_status=False)
    qtbot.addWidget(restarted)
    assert restarted.workstations[0].agent_status == AgentStatus.ONLINE
    assert restarted.workstations[0].current_session_user == "TARGET\\tester"


def test_machine_specific_fallback_reads_its_exact_folder(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "portal-state.json")
    store.save([Workstation("PILOT", "Pilot", "target")], MockUser.create_user(), [])
    path = write_agent_snapshot(AgentSnapshot("PILOT", "target", "1"), tmp_path / "actual folder")
    store.set_workstation_agent_status_directory("PILOT", path.parent)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    assert window.workstations[0].agent_fallback_directory == str(path.parent)
    assert window.workstations[0].agent_fallback_is_explicit
    assert window.workstations[0].agent_status == AgentStatus.ONLINE


def test_each_machine_reads_only_its_own_fallback_folder(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    write_agent_snapshot(AgentSnapshot("WS-1", "one", "1"), first_dir)
    write_agent_snapshot(AgentSnapshot("WS-2", "two", "1"), second_dir)
    first = Workstation(
        "WS-1", "One", "one", agent_fallback_directory=str(first_dir),
        agent_fallback_is_explicit=True,
    )
    second = Workstation(
        "WS-2", "Two", "two", agent_fallback_directory=str(second_dir),
        agent_fallback_is_explicit=True,
    )
    service = LocalAgentStatusService(directory=tmp_path / "unused")
    service.apply([first, second])
    assert first.agent_status_source == second.agent_status_source == "file"
    assert service.last_match_count == 2
    assert service.last_snapshot_count == 2
    assert service.directory_summary == "2 maschinenspezifische Fallbackordner"


def test_machine_fallback_paths_survive_restart_independently(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    first = store.set_workstation_agent_status_directory("WS-1", tmp_path / "one")
    second = store.set_workstation_agent_status_directory("WS-2", tmp_path / "two")
    restored = LocalStore(store.path)
    assert restored.get_workstation_agent_status_directory("ws-1") == (first, True)
    assert restored.get_workstation_agent_status_directory("WS-2") == (second, True)


def test_nb05_assignment_updates_real_card_and_survives_restart(tmp_path, monkeypatch, qtbot):
    from PySide6.QtWidgets import QLabel
    from portal_app.ui.widgets.workstation_cards import WorkstationCard

    store = LocalStore(tmp_path / "portal-state.json")
    store.save([Workstation("PORTAL-123", "NB05", "192.168.2.74")], MockUser.create_user(), [])
    directory = tmp_path / "agenten-status"
    store.set_agent_status_directory(directory)
    write_agent_snapshot(AgentSnapshot("NB05", "NB05", "1.0.0"), directory)
    for old_id in ("NB05-PC12", "NB05-PC12-2"):
        write_agent_snapshot(AgentSnapshot(old_id, "NB05", "1.0.0", observed_at_utc=datetime.now(timezone.utc) - timedelta(days=1)), directory)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    assert window.agent_status_service.last_snapshot_count == 3
    assert window.agent_status_service.last_match_count == 0
    window.on_workstation_selected(window.workstations[0])
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getItem",
                        lambda *args: (next(label for label in args[3] if label.startswith("NB05 ·")), True))
    window.detail_view.agent_assignment_btn.click()
    assert window.workstations[0].hostname == "192.168.2.74"
    assert window.workstations[0].workstation_id == "PORTAL-123"
    assert window.workstations[0].agent_workstation_id == "NB05"
    assert "1 online" in window.summary.text()
    assert "NB05" in window.detail_view.agent_assignment_label.text()
    card = next(c for c in window.overview_view._cards if isinstance(c, WorkstationCard))
    assert "Online" in card.findChild(QLabel, "cardStatus").text()
    assert any(label.text() == "Frei und verfügbar" for label in card.findChildren(QLabel))
    write_agent_snapshot(AgentSnapshot("NB05", "NB05", "1.0.0", current_session_state=SessionState.CONNECTED, current_session_user="NB05\\tester"), directory)
    window.agent_poll_timer.start(10)
    qtbot.waitUntil(lambda: window.workstations[0].current_session_user == "NB05\\tester")
    window.agent_poll_timer.stop()
    card = next(c for c in window.overview_view._cards if isinstance(c, WorkstationCard))
    assert any("Belegt von NB05\\tester" == label.text() for label in card.findChildren(QLabel))
    restarted_store = LocalStore(store.path)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: restarted_store)
    restarted = MainWindow(automatic_live_status=False)
    qtbot.addWidget(restarted)
    assert restarted.workstations[0].agent_workstation_id == "NB05"
    assert restarted.workstations[0].agent_status == AgentStatus.ONLINE


def test_explicit_agent_binding_prevents_hostname_fallback_and_double_assignment(tmp_path):
    write_agent_snapshot(AgentSnapshot("NB05", "NB05", "1"), tmp_path)
    service = LocalAgentStatusService(directory=tmp_path)
    first = Workstation("A", "A", "192.168.2.74", agent_workstation_id="NB05")
    second = Workstation("B", "B", "NB05")
    service.apply([first, second])
    assert first.agent_status == AgentStatus.ONLINE
    assert second.agent_status == AgentStatus.OFFLINE
    second.agent_workstation_id = "NB05"
    service.apply([first, second])
    assert service.last_match_count == 0
    assert "mehrfach" in second.agent_diagnostic
    second.agent_workstation_id = "DIFFERENT"
    service.apply([second])
    assert service.last_match_count == 0


def test_failed_agent_binding_save_rolls_back(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "portal-state.json")
    store.save([Workstation("A", "NB05", "192.168.2.74")], MockUser.create_user(), [])
    directory = tmp_path / "agenten-status"
    store.set_agent_status_directory(directory)
    write_agent_snapshot(AgentSnapshot("NB05", "NB05", "1"), directory)
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getItem", lambda *a: (a[3][1], True))
    monkeypatch.setattr(window, "_persist", lambda: False)
    window._assign_agent(window.workstations[0])
    assert window.workstations[0].agent_workstation_id is None
    assert window._saved_workstations[0].agent_workstation_id is None
