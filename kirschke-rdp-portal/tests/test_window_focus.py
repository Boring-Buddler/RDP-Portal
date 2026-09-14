"""Das Fenster-Hervorholen ersetzt die Sackgasse "ein Fenster laeuft bereits"."""

from unittest.mock import Mock

from portal_app.rdp.launcher import RDPSessionLauncher, TrackedRDPSession
from portal_app.rdp.window_focus import windows_of_processes


def tracked(pid: int, workstation_id: str) -> TrackedRDPSession:
    from datetime import datetime
    process = Mock()
    process.poll.return_value = None
    return TrackedRDPSession(pid=pid, workstation_id=workstation_id, display_name=workstation_id,
                             target="t", started_at=datetime.now(), rdp_file="x.rdp", process=process)


def test_only_windows_of_the_portals_own_processes_are_considered(monkeypatch):
    """Sonst koennte das Portal ein fremdes Fenster in den Vordergrund reissen."""
    launcher = RDPSessionLauncher()
    launcher._active_sessions = {11: tracked(11, "A"), 22: tracked(22, "B")}
    seen = []
    monkeypatch.setattr("portal_app.rdp.window_focus.focus_windows",
                        lambda pids: seen.append(list(pids)) or True)

    assert launcher.focus_session("A") is True
    assert seen == [[11]]


def test_focusing_a_machine_without_a_window_reports_failure(monkeypatch):
    launcher = RDPSessionLauncher()
    monkeypatch.setattr("portal_app.rdp.window_focus.focus_windows", lambda pids: bool(list(pids)))

    assert launcher.focus_session("nicht-gestartet") is False


def test_an_empty_process_list_enumerates_nothing():
    assert windows_of_processes([]) == []


def test_the_portals_own_process_has_a_findable_window(qtbot):
    """Gegenprobe gegen die echte Windows-API statt gegen einen Mock."""
    import os

    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setWindowTitle("Fenstersuche")
    widget.show()
    qtbot.waitExposed(widget)

    assert windows_of_processes([os.getpid()])
