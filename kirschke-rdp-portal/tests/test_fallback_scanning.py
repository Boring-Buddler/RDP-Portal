"""Regression guard for finding ST1: the heartbeat must not read SMB on the UI thread.

``_poll_agent_status`` claimed "without blocking the UI" while
``LocalAgentStatusService.apply`` ran iterdir/read_bytes/json.loads against UNC
paths in the Qt main thread.  An unreachable share froze the window for the SMB
timeout every few seconds.
"""

import threading
import time

import pytest

from portal_app.models.user import MockUser
from portal_app.services import agent_status as agent_status_module
from portal_app.services.agent_status import DirectoryScan, LocalAgentStatusService
from portal_app.services.fallback_scanning import FallbackScanner
from portal_app.services.local_store import LocalStore
from portal_app.ui.main_window import MainWindow
from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot
from shared.enums import AgentStatus, SessionState


def _machine(workstation_id: str = "WS-1"):
    from portal_app.models.workstation import Workstation

    return Workstation(
        workstation_id=workstation_id,
        hostname=workstation_id,
        display_name=workstation_id,
    )


# --------------------------------------------------------------------------
# The service split: scanning and applying are separable
# --------------------------------------------------------------------------


def test_scan_directories_is_a_staticmethod_free_of_service_state() -> None:
    """It must be callable from a worker without touching the service instance."""
    assert isinstance(
        LocalAgentStatusService.__dict__["scan_directories"], staticmethod
    )


def test_scan_then_apply_matches_the_blocking_apply(tmp_path) -> None:
    directory = tmp_path / "agent-status"
    directory.mkdir()
    write_agent_snapshot(
        AgentSnapshot(
            "WS-1",
            "WS-1",
            "1.3.0",
            current_session_state=SessionState.CONNECTED,
            current_session_user="KIRSCHKE\\tester",
        ),
        directory,
    )

    inline_service = LocalAgentStatusService(directory=directory)
    inline = [_machine()]
    inline_service.apply(inline)

    split_service = LocalAgentStatusService(directory=directory)
    split = [_machine()]
    directories = split_service.fallback_directories(split)
    scans = split_service.scan_directories(directories)
    split_service.apply_scans(split, scans)

    assert inline[0].agent_status == split[0].agent_status == AgentStatus.ONLINE
    assert inline[0].current_session_user == split[0].current_session_user
    assert inline_service.last_match_count == split_service.last_match_count == 1


def test_apply_scans_tolerates_a_folder_that_changed_during_the_scan(tmp_path) -> None:
    """The config can change between the worker read and the UI apply."""
    service = LocalAgentStatusService(directory=tmp_path / "gone")
    machines = [_machine()]
    # Deliberately hand over a scan for an unrelated folder.
    stale = {"c:\\\\somewhere-else": DirectoryScan(tmp_path / "somewhere-else")}
    changed = service.apply_scans(machines, stale)
    assert isinstance(changed, int)
    assert machines[0].agent_status == AgentStatus.OFFLINE


# --------------------------------------------------------------------------
# FallbackScanner
# --------------------------------------------------------------------------


def test_scanner_reads_in_a_background_thread(qapp, tmp_path, qtbot) -> None:
    directory = tmp_path / "agent-status"
    directory.mkdir()
    write_agent_snapshot(AgentSnapshot("WS-1", "WS-1", "1.3.0"), directory)

    scanner = FallbackScanner()
    main_thread = threading.current_thread().ident
    worker_threads: list[int | None] = []
    original = LocalAgentStatusService.scan_directories

    def recording(directories):
        worker_threads.append(threading.current_thread().ident)
        return original(directories)

    try:
        LocalAgentStatusService.scan_directories = staticmethod(recording)
        received: list[object] = []
        scanner.completed.connect(received.append)
        assert scanner.request({str(directory).casefold(): directory}) is True
        with qtbot.waitSignal(scanner.completed, timeout=5000):
            pass
    finally:
        LocalAgentStatusService.scan_directories = staticmethod(original)
        scanner.stop()

    assert worker_threads, "scan_directories was never called"
    assert worker_threads[0] != main_thread, "the folder read stayed on the UI thread"
    assert received and isinstance(received[0], dict)


def test_scanner_drops_an_overlapping_request(qapp, tmp_path, qtbot) -> None:
    directory = tmp_path / "slow"
    directory.mkdir()
    release = threading.Event()
    original = LocalAgentStatusService.scan_directories

    def slow(directories):
        release.wait(timeout=5)
        return original(directories)

    scanner = FallbackScanner()
    try:
        LocalAgentStatusService.scan_directories = staticmethod(slow)
        assert scanner.request({"a": directory}) is True
        # Second request while the first still runs must be refused, not queued.
        assert scanner.request({"a": directory}) is False
        assert scanner.busy is True
        release.set()
        with qtbot.waitSignal(scanner.completed, timeout=5000):
            pass
        assert scanner.busy is False
        assert scanner.request({"a": directory}) is True
        with qtbot.waitSignal(scanner.completed, timeout=5000):
            pass
    finally:
        release.set()
        LocalAgentStatusService.scan_directories = staticmethod(original)
        scanner.stop()


def test_scanner_reports_a_failing_scan_as_per_folder_errors(qapp, tmp_path, qtbot) -> None:
    original = LocalAgentStatusService.scan_directories
    scanner = FallbackScanner()
    results: list[object] = []
    try:
        LocalAgentStatusService.scan_directories = staticmethod(
            lambda directories: (_ for _ in ()).throw(RuntimeError("Netzwerk weg"))
        )
        scanner.completed.connect(results.append)
        scanner.request({"key": tmp_path})
        with qtbot.waitSignal(scanner.completed, timeout=5000):
            pass
    finally:
        LocalAgentStatusService.scan_directories = staticmethod(original)
        scanner.stop()
    assert results
    scan = results[0]["key"]
    assert scan.files == []
    assert any("Netzwerk weg" in message for message in scan.errors)


def test_scanner_refuses_requests_after_stop(qapp, tmp_path) -> None:
    scanner = FallbackScanner()
    scanner.stop()
    assert scanner.request({"key": tmp_path}) is False


# --------------------------------------------------------------------------
# MainWindow wiring
# --------------------------------------------------------------------------


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "state.json")
    store.save([_machine()], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    created = MainWindow(automatic_live_status=False)
    qtbot.addWidget(created)
    yield created
    created.fallback_scanner.stop()


def test_heartbeat_does_not_scan_on_the_ui_thread(window, monkeypatch) -> None:
    """_scheduled_status_update must delegate the read, never perform it."""
    calls: list[str] = []
    monkeypatch.setattr(
        agent_status_module.LocalAgentStatusService,
        "scan_directories",
        staticmethod(lambda directories: calls.append("inline") or {}),
    )
    requested: list[dict] = []
    monkeypatch.setattr(
        window.fallback_scanner, "request", lambda directories: requested.append(directories) or True
    )

    window._scheduled_status_update()

    assert requested, "the heartbeat did not hand the scan to the background scanner"
    assert calls == [], "the heartbeat read the folders on the UI thread"


def test_explicit_poll_still_applies_synchronously(window, tmp_path) -> None:
    """Startup, user actions and tests rely on the blocking contract."""
    write_agent_snapshot(AgentSnapshot("WS-1", "WS-1", "1.3.0"), tmp_path / "agent-status")
    window._poll_agent_status()
    assert window.workstations[0].agent_status == AgentStatus.ONLINE


def test_background_result_is_applied_to_the_machine_list(window, tmp_path, qtbot) -> None:
    write_agent_snapshot(AgentSnapshot("WS-1", "WS-1", "1.3.0"), tmp_path / "agent-status")
    window.workstations[0].agent_status = AgentStatus.OFFLINE

    with qtbot.waitSignal(window.fallback_scanner.completed, timeout=5000):
        window._poll_agent_status(blocking=False)

    assert window.workstations[0].agent_status == AgentStatus.ONLINE
    assert "1/1" in window.overview_view.agent_channel_status.text()


def test_a_slow_share_does_not_stall_the_heartbeat(window, tmp_path, qtbot) -> None:
    """The UI thread must return immediately even while a scan is blocked."""
    release = threading.Event()
    original = LocalAgentStatusService.scan_directories

    def slow(directories):
        release.wait(timeout=5)
        return original(directories)

    try:
        LocalAgentStatusService.scan_directories = staticmethod(slow)
        started = time.monotonic()
        window._poll_agent_status(blocking=False)
        elapsed = time.monotonic() - started
        # The scan is still blocked in the worker; the call must already be back.
        assert elapsed < 0.5, f"the heartbeat blocked for {elapsed:.2f}s"
        assert window.fallback_scanner.busy is True
    finally:
        release.set()
        LocalAgentStatusService.scan_directories = staticmethod(original)
        with qtbot.waitSignal(window.fallback_scanner.completed, timeout=5000):
            pass
