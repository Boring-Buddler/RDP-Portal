from datetime import datetime, timezone

from PySide6.QtCore import QProcess

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.workstation_cards import WorkstationCard, WorkstationCardsWidget
from shared.enums import AgentStatus, SessionState
from workstation_agent.session_history import SessionHistory
from workstation_agent.wts.monitor import WTSMonitor, WTSSessionInfo


def test_machine_installer_in_isolated_filesystem(tmp_path):
    import subprocess
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(project / "tests/check_agent_installer.ps1"), "-Project", str(project), "-TestRoot", str(tmp_path)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_portal_uninstaller_preserves_inventory(tmp_path):
    import subprocess
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(project / "tests/check_portal_uninstaller.ps1"), "-Project", str(project), "-TestRoot", str(tmp_path)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_sessions_and_history_reach_portal_details(tmp_path, qtbot):
    from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot
    from portal_app.services.agent_status import LocalAgentStatusService
    from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
    sessions = [dict(session_id=1, username="console", domain="PC", session_state="connected", login_time="2026-09-10T08:00:00+00:00"),
                dict(session_id=2, username="remote", domain="PC", session_state="disconnected", login_time="2026-09-10T09:00:00+00:00")]
    history = [dict(sessions[0], observed_at_utc="2026-09-10T08:00:10+00:00", event="Sitzung erkannt")]
    write_agent_snapshot(AgentSnapshot("A", "PC", "1.1.0", rdp_sessions=sessions, session_history=history,
                                      current_session_user="PC\\console", current_session_state=SessionState.CONNECTED), tmp_path)
    ws = Workstation("A", "A", "PC")
    LocalAgentStatusService(directory=tmp_path).apply([ws])
    detail = WorkstationDetailWidget(MockUser.create_user())
    qtbot.addWidget(detail)
    detail.set_workstation(ws)
    assert "PC\\console" in detail.value_labels["all_sessions"].text()
    assert "PC\\remote" in detail.value_labels["all_sessions"].text()
    assert "2026-09-10T08:00:00" in detail.value_labels["all_sessions"].text()
    assert "Sitzung erkannt" in detail.value_labels["session_history"].text()


def test_console_and_disconnected_users_are_included(monkeypatch):
    monitor = WTSMonitor()
    sessions = [WTSSessionInfo(0), WTSSessionInfo(1, username="console", protocol_type=0),
                WTSSessionInfo(2, username="remote", protocol_type=2, session_state=SessionState.DISCONNECTED)]
    monkeypatch.setattr(monitor, "get_all_sessions", lambda: sessions)
    assert [s.username for s in monitor.get_user_sessions()] == ["console", "remote"]


def test_history_persists_transitions_and_does_not_repeat_heartbeats(tmp_path):
    path = tmp_path / "history.json"
    history = SessionHistory(path)
    session = dict(session_id=1, username="tester", domain="PC", login_time=datetime.now(timezone.utc).isoformat(), session_state="connected")
    history.observe([session])
    history.observe([session])
    assert len(history.events) == 1
    restored = SessionHistory(path)
    restored.observe([dict(session, session_state="disconnected")])
    restored.observe([])
    assert [e["event"] for e in restored.events] == ["Sitzung erkannt", "Sitzung geändert", "Nicht mehr gemeldet"]
    assert restored.events[0]["login_time"] == session["login_time"]


def test_history_write_failure_keeps_previous_state(tmp_path, monkeypatch):
    history = SessionHistory(tmp_path / "history.json")
    def fail(*args):
        raise PermissionError("denied")
    monkeypatch.setattr("workstation_agent.session_history.write_json_atomic", fail)
    import pytest
    with pytest.raises(PermissionError):
        history.observe([dict(session_id=1, username="u")])
    assert history.current == {} and history.events == []


def test_ping_latency_stays_in_card_corner_after_agent_refresh(qtbot, monkeypatch):
    ws = Workstation("A", "A", "localhost", agent_status=AgentStatus.ONLINE)
    view = WorkstationCardsWidget([ws], MockUser.create_user())
    qtbot.addWidget(view)
    card = next(c for c in view._cards if isinstance(c, WorkstationCard))
    monkeypatch.setattr(card, "_ping_latency", lambda: "<1")
    card._on_ping_finished(0, QProcess.NormalExit)
    assert card.ping_result.text() == "<1 ms"
    assert card.ping_btn.text() == "Ping"
    view.set_workstations([ws])
    card = next(c for c in view._cards if isinstance(c, WorkstationCard))
    assert card.ping_result.text() == "<1 ms"
    free_color = card._accent_color()
    ws.current_session_state = SessionState.CONNECTED
    ws.current_session_user = "PC\\tester"
    assert card._accent_color() != free_color
    card._on_ping_finished(1, QProcess.NormalExit)
    assert card.ping_result.text() == "Keine Ping-Antwort"
    assert ws.agent_status == AgentStatus.ONLINE
