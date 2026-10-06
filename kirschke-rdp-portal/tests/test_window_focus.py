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


def test_windowless_process_stops_blocking_but_late_window_is_recognised(monkeypatch):
    launcher = RDPSessionLauncher()
    session = tracked(11, "A")
    session.last_window_at = 0
    launcher._active_sessions[11] = session
    monkeypatch.setattr("portal_app.rdp.launcher.time.monotonic", lambda: 31)
    windows = Mock(return_value=[])
    monkeypatch.setattr("portal_app.rdp.window_focus.windows_of_processes", windows)
    assert not launcher.has_active_session("A")
    assert launcher.consume_finished_sessions() == [session]
    assert launcher.consume_finished_sessions() == []
    session.process.terminate.assert_not_called()
    windows.return_value = [123]
    # Erkannt wird das späte Fenster mit der nächsten Aufzählung, also nach
    # Ablauf der Frist, für die has_active_session das letzte Ergebnis behält.
    monkeypatch.setattr("portal_app.rdp.launcher.time.monotonic", lambda: 33)
    assert launcher.has_active_session("A")


def test_startup_grace_and_window_enumeration_failure_prevent_duplicate_launch(monkeypatch):
    launcher = RDPSessionLauncher()
    session = tracked(11, "A")
    session.last_window_at = 0
    launcher._active_sessions[11] = session
    monkeypatch.setattr("portal_app.rdp.launcher.time.monotonic", lambda: 10)
    windows = Mock(return_value=[])
    monkeypatch.setattr("portal_app.rdp.window_focus.windows_of_processes", windows)
    assert launcher.has_active_session("A")
    windows.side_effect = OSError("enumeration failed")
    monkeypatch.setattr("portal_app.rdp.launcher.time.monotonic", lambda: 100)
    assert launcher.has_active_session("A")


def test_focus_does_not_claim_success_when_windows_refuses(monkeypatch):
    from portal_app.rdp import window_focus
    monkeypatch.setattr(window_focus, "windows_of_processes", lambda _: [123])
    monkeypatch.setattr(window_focus.user32, "IsIconic", lambda _: False)
    monkeypatch.setattr(window_focus.user32, "SetForegroundWindow", lambda _: False)
    assert not window_focus.focus_windows([11])


def test_focus_handles_failed_window_enumeration(monkeypatch):
    from portal_app.rdp import window_focus
    monkeypatch.setattr(window_focus, "windows_of_processes", Mock(side_effect=OSError()))
    assert not window_focus.focus_windows([11])


def test_owned_dialog_is_recognised_as_a_live_rdp_client_window(qtbot):
    import os

    from PySide6.QtWidgets import QDialog, QWidget

    owner = QWidget()
    qtbot.addWidget(owner)
    dialog = QDialog(owner)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert int(dialog.winId()) in windows_of_processes([os.getpid()])


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
