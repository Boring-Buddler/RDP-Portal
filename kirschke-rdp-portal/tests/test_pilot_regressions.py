"""Regression coverage for data loss, unsafe RDP output and agent failures."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.rdp.generator import RDPFileGenerator, RDPGenerationError
from portal_app.rdp.launcher import RDPSessionLauncher
from portal_app.services.admin_security import LocalAdminPasswordStore
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.local_store import LocalStore, StoreConflictError, StoreReadError
from shared.agent_snapshot import AgentSnapshot, load_agent_snapshots, write_agent_snapshot
from shared.enums import AgentStatus, EventType, SessionState
from shared.file_io import file_lock
from shared.schemas import RDPProfileSchema
from workstation_agent.eventlog.handler import AgentSessionEvent, EventLogConfig, EventQueue
from workstation_agent.service import AgentConfig, WorkstationAgent
from workstation_agent.wts.monitor import WTSMonitor


def machine(identifier="WS-1"):
    return Workstation(workstation_id=identifier, display_name=identifier, hostname=identifier)


@pytest.mark.parametrize("content", ["{broken", "[]", "null", '{"version":99}', '{"workstations":[{}]}'])
def test_bad_existing_state_is_preserved(tmp_path, content):
    path = tmp_path / "portal-state.json"
    path.write_text(content, encoding="utf-8")
    store = LocalStore(path)
    with pytest.raises(StoreReadError):
        store.load([machine()], MockUser.create_user())
    with pytest.raises(StoreReadError):
        store.save([], MockUser.create_user(), [])
    assert path.read_text(encoding="utf-8") == content


def test_empty_saved_inventory_stays_empty(tmp_path):
    store = LocalStore(tmp_path / "state.json")
    store.save([], MockUser.create_user(), [])
    assert store.load([machine()], MockUser.create_user())[0] == []


def test_second_save_preserves_unseen_remote_addition(tmp_path):
    path = tmp_path / "state.json"
    user = MockUser.create_user()
    first, second = LocalStore(path), LocalStore(path)
    first.save([machine()], user, [])
    left = first.load([], user)[0]
    right = second.load([], user)[0]
    first.save(left + [machine("WS-2")], user, [])
    right[0].display_name = "Edited"
    second.save(right, user, [])
    second.save(right, user, [], "dark")
    assert {ws.workstation_id for ws in LocalStore(path).load([], user)[0]} == {"WS-1", "WS-2"}


def test_event_append_does_not_hide_changed_inventory(tmp_path):
    store = LocalStore(tmp_path / "state.json")
    user = MockUser.create_user()
    store.save([], user, [])
    store.load([], user)
    other = LocalStore(store.path)
    other.save([machine()], user, [])
    store.append_event(SessionEvent("E1", datetime.now(), EventType.LAUNCH_REQUESTED, "WS-1"))
    assert store.has_external_changes()


def test_parallel_reservations_cannot_overlap(tmp_path):
    user = MockUser.create_user()
    first = LocalStore(tmp_path / "state.json")
    first.save([machine()], user, [])
    second = LocalStore(first.path)
    workstations = second.load([], user)[0]
    start = datetime(2026, 9, 10, 10)
    first.save(workstations, user, [Reservation("WS-1", "A", start, start + timedelta(hours=2), "A")])
    with pytest.raises(StoreConflictError):
        second.save(workstations, user, [Reservation("WS-1", "B", start, start + timedelta(hours=1), "B")])
    assert first.load([], user)[2][0].title == "A"


def test_file_lock_rejects_second_writer(tmp_path):
    path = tmp_path / "state.lock"
    with file_lock(path):
        with pytest.raises(TimeoutError):
            with file_lock(path, timeout=0.05):
                pytest.fail("Second writer entered locked region")
    with file_lock(path):
        pass


@pytest.mark.parametrize("field", ["username_hint", "display_name", "hostname", "gateway_hostname"])
def test_rdp_output_rejects_injected_properties(tmp_path, field):
    profile = RDPProfileSchema(hostname="WS-1", display_name="Test")
    setattr(profile, field, "safe\nauthentication level:i:0")
    with pytest.raises(RDPGenerationError):
        RDPFileGenerator(str(tmp_path)).generate(profile)
    assert not list(tmp_path.glob("*.rdp"))


@pytest.mark.parametrize("redirect,screen", [(False, "windowed"), (True, "fullscreen")])
def test_rdp_options_and_file_validation(tmp_path, redirect, screen):
    profile = RDPProfileSchema(hostname="WS-1", display_name="Test", redirect_audio=redirect,
                               redirect_drives=redirect, screen_mode=screen, resolution="1920x1080",
                               gateway_hostname="gateway.example.test")
    generator = RDPFileGenerator(str(tmp_path))
    path = generator.generate(profile)
    content = Path(path).read_text(encoding="utf-8")
    assert f"audiomode:i:{0 if redirect else 2}" in content
    assert f"drivestoredirect:s:{'*' if redirect else ''}\n" in content
    assert f"screen mode id:i:{2 if screen == 'fullscreen' else 1}" in content
    assert "gatewayusagemethod:i:1" in content
    assert RDPSessionLauncher(generator).test_rdp_file(path)[0]


def test_missing_snapshot_ages_previous_observation(tmp_path):
    ws = machine()
    ws.agent_status = AgentStatus.ONLINE
    ws.agent_last_seen_utc = datetime.now(UTC) - timedelta(minutes=6)
    ws.current_session_state = SessionState.DISCONNECTED
    LocalAgentStatusService(directory=tmp_path).apply([ws])
    assert ws.agent_status == AgentStatus.OFFLINE
    assert ws.has_active_session()


def test_snapshot_exact_id_wins_over_hostname_alias(tmp_path):
    ws = machine()
    ws.hostname = "same-host"
    write_agent_snapshot(AgentSnapshot("WS-1", "same-host", "1", current_session_state=SessionState.DISCONNECTED), tmp_path)
    write_agent_snapshot(AgentSnapshot("WS-2", "same-host", "1"), tmp_path)
    LocalAgentStatusService(directory=tmp_path).apply([ws])
    assert ws.current_session_state == SessionState.DISCONNECTED


@pytest.mark.parametrize("data", [[], None, {"version": 9}, {"version": 1, "workstation_id": 7}])
def test_malformed_snapshots_are_ignored(tmp_path, data):
    (tmp_path / "bad.json").write_text(json.dumps(data), encoding="utf-8")
    assert load_agent_snapshots(tmp_path) == []


def test_future_snapshot_is_not_online(tmp_path):
    snapshot = AgentSnapshot("WS-1", "WS-1", "1", observed_at_utc=datetime.now(UTC) + timedelta(days=1))
    write_agent_snapshot(snapshot, tmp_path)
    ws = machine()
    LocalAgentStatusService(directory=tmp_path).apply([ws])
    assert ws.agent_status == AgentStatus.ERROR


def test_wts_error_is_not_an_empty_session_list(monkeypatch):
    monkeypatch.setattr("workstation_agent.wts.monitor.wtsapi32.WTSEnumerateSessionsW", lambda *args: False)
    with WTSMonitor() as monitor, pytest.raises(OSError):
        monitor.get_rdp_sessions()


def test_agent_reads_powershell_bom_and_false_values(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({"workstation_id": "PILOT", "publish_local_status": False, "log_file": str(tmp_path / "a.log")}), encoding="utf-8-sig")
    monkeypatch.setenv("AGENT_CONFIG_PATH", str(path))
    monkeypatch.delenv("WORKSTATION_ID", raising=False)
    monkeypatch.delenv("AGENT_PUBLISH_LOCAL_STATUS", raising=False)
    config = AgentConfig.from_env()
    assert config.workstation_id == "PILOT"
    assert config.publish_local_status is False


def test_agent_config_file_wins_over_inherited_service_environment(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    path.write_text(json.dumps({
        "workstation_id": "PILOT",
        "log_file": str(tmp_path / "agent.log"),
        "status_directory": str(tmp_path / "agent-status"),
    }), encoding="utf-8-sig")
    monkeypatch.setenv("AGENT_CONFIG_PATH", str(path))
    monkeypatch.setenv("AGENT_LOG_FILE", r"C:\\ProgramData\\KirschkeRDPAgent\\logs\\agent.log")
    monkeypatch.setenv("AGENT_STATUS_DIR", r"C:\\ProgramData\\KirschkeRDPAgent\\status")
    config = AgentConfig.from_env()
    assert config.log_file == str(tmp_path / "agent.log")
    assert config.status_directory == str(tmp_path / "agent-status")


def test_agent_continues_when_file_log_cannot_be_opened(tmp_path, monkeypatch):
    config = AgentConfig(
        workstation_id="PILOT",
        log_file=str(tmp_path / "blocked" / "agent.log"),
        status_directory=str(tmp_path / "agent-status"),
    )
    monkeypatch.setattr("logging.handlers.RotatingFileHandler", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")))
    agent = WorkstationAgent(config)
    agent._publish_local_snapshot()
    assert (tmp_path / "agent-status" / "PILOT.json").is_file()


def test_agent_rejects_invalid_explicit_config(tmp_path, monkeypatch):
    path = tmp_path / "agent.json"
    path.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("AGENT_CONFIG_PATH", str(path))
    with pytest.raises(ValueError):
        AgentConfig.from_env()


def test_event_queue_survives_restart_with_typed_events(tmp_path):
    config = EventLogConfig(log_directory=str(tmp_path), persist_events=True)
    queue = EventQueue(config)
    event = AgentSessionEvent(workstation_id="WS-1", event_type=EventType.RDP_LOGON)
    queue.add_event(event)
    restarted = EventQueue(config)
    recovered = restarted.get_unsent_events()[0]
    assert recovered.event_type == event.event_type
    assert recovered.timestamp_utc == event.timestamp_utc
    restarted.mark_event_sent(recovered.event_id)
    assert EventQueue(config).get_unsent_events() == []


def test_agent_detector_uses_submission_queue(tmp_path):
    agent = WorkstationAgent(AgentConfig(workstation_id="PILOT", log_file="", publish_local_status=False))
    agent._event_queue = EventQueue(EventLogConfig(log_directory=str(tmp_path), persist_events=True))
    detector = agent._get_event_detector()
    assert detector.event_queue is agent._get_event_queue()
    agent.stop()


def test_remote_commands_do_not_execute_in_pilot():
    agent = WorkstationAgent(AgentConfig(workstation_id="PILOT", log_file="", publish_local_status=False))
    agent._graph_client = Mock()
    agent.command_handler = Mock()
    agent._check_admin_commands()
    agent._graph_client.get_pending_commands.assert_not_called()
    agent.command_handler.execute_command.assert_not_called()


@pytest.mark.parametrize("content", ["broken", "[]", '{"iterations":-1,"salt":"AA==","password_hash":"AA=="}'])
def test_corrupt_admin_file_does_not_reopen_setup(tmp_path, content):
    store = LocalAdminPasswordStore(tmp_path / "admin.json")
    store.path.write_text(content, encoding="utf-8")
    assert store.is_configured()
    assert not store.verify_password("any password")


def test_event_timestamps_have_utc_offsets():
    event = SessionEvent("E1", datetime(2026, 9, 9, 12, tzinfo=timezone(timedelta(hours=2))), EventType.RDP_LOGON, "WS-1")
    assert event.timestamp_utc.hour == 10
    assert event.to_schema().model_dump(mode="json")["timestamp_utc"].endswith(("Z", "+00:00"))


def test_preflight_does_not_rewrite_inventory(tmp_path):
    from portal_app.preflight import inspect_pilot

    store = LocalStore(tmp_path / "portal-state.json")
    store.save([machine()], MockUser.create_user(), [])
    before = store.path.read_bytes()
    checks = inspect_pilot(tmp_path)
    assert not any(check["status"] == "error" for check in checks)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("target", ["999.1.2.3", "pc.example.test\n"])
def test_invalid_rdp_target_is_rejected(target):
    from shared.validation import RDPProfileValidator, RDPValidationError

    with pytest.raises(RDPValidationError):
        RDPProfileValidator.validate_hostname(target)


def test_ipv6_rdp_target_is_bracketed(tmp_path):
    profile = RDPProfileSchema(hostname="2001:db8::1", display_name="IPv6")
    filename = RDPFileGenerator(str(tmp_path)).generate(profile)
    assert "full address:s:[2001:db8::1]" in Path(filename).read_text(encoding="utf-8")
    assert RDPSessionLauncher().test_rdp_file(filename)[0]


def test_deleted_state_is_not_treated_as_a_new_installation(tmp_path):
    store = LocalStore(tmp_path / "state.json")
    user = MockUser.create_user()
    store.save([machine()], user, [])
    store.path.unlink()
    with pytest.raises(StoreReadError):
        store.load([], user)


def test_agent_poll_does_not_persist_unsaved_machine_edits(tmp_path, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    store = LocalStore(tmp_path / "state.json")
    store.save([machine()], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    window.workstations[0].display_name = "Unsaved edit"
    write_agent_snapshot(AgentSnapshot("WS-1", "WS-1", "1"), tmp_path / "agent-status")
    window._poll_agent_status()
    assert window.workstations[0].agent_status == AgentStatus.ONLINE
    assert LocalStore(store.path).load([], MockUser.create_user())[0][0].display_name == "WS-1"


def test_log_displays_utc_event_with_local_date_filter(qtbot):
    from portal_app.ui.widgets.session_log import SessionLogWidget

    widget = SessionLogWidget([], MockUser.create_user())
    qtbot.addWidget(widget)
    widget.set_events([SessionEvent("EVT-UTC", datetime.now(UTC), EventType.RDP_LOGON, "WS-1")])
    assert widget.table.rowCount() == 1
    assert widget.table.item(0, 2).text() == "WS-1"
