"""Netz- und Fensterabfragen dürfen den UI-Thread nicht anhalten.

Drei Stellen haben das Portal spürbar zäh gemacht:

* Jede Live-Antwort las alle Fallbackordner blockierend neu ein -- pro Maschine
  und Statuslauf ein SMB-Scan im UI-Thread.
* Offene Aufschaltmeldungen gingen im Statustakt synchron über die Pipe; gegen
  eine abgeschaltete Maschine hing das Fenster jedes Mal sekundenlang.
* Jede Karte fragte bei jedem Neuzeichnen per EnumWindows nach offenen
  RDP-Fenstern.
"""

from __future__ import annotations

import threading
import time

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.rdp import launcher as launcher_module
from portal_app.rdp.generator import RDPFileGenerator
from portal_app.rdp.launcher import RDPSessionLauncher
from portal_app.services import session_claims
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.local_store import LocalStore
from portal_app.services.session_claims import BackgroundSessionClaimReporter
from portal_app.ui.main_window import MainWindow
from portal_app.ui.stall_watchdog import UiStallWatchdog
from shared import name_resolution
from shared.agent_snapshot import AgentSnapshot
from shared.enums import AgentStatus, SessionState

SHARED_ACCOUNT = "WORKSTATION\\Rechenknecht"


def _person() -> MockUser:
    user = MockUser.create_user()
    user.upn = "a@x.de"
    user.display_name = "Becker"
    return user


def _machine_with_session() -> Workstation:
    machine = Workstation(
        "WS-1",
        "Workstation",
        "WORKSTATION",
        agent_status=AgentStatus.ONLINE,
        current_session_state=SessionState.CONNECTED,
        current_session_user=SHARED_ACCOUNT,
        agent_sessions=[
            {
                "session_id": 3,
                "full_username": SHARED_ACCOUNT,
                "session_state": SessionState.CONNECTED.value,
                "login_time": "2026-09-16T08:00:00+00:00",
            }
        ],
    )
    machine.agent_status_source = "live"
    return machine


# --- Aufschaltmeldungen im Hintergrund ---------------------------------------


def test_a_report_returns_while_the_pipe_still_waits(monkeypatch, qtbot) -> None:
    release = threading.Event()
    calls: list[str] = []

    def slow_pipe(target, claim, pipe_name=None, credentials=None):
        calls.append(target)
        release.wait(timeout=5)
        return claim["account"]

    monkeypatch.setattr(session_claims, "push_session_claim", slow_pipe)
    reporter = BackgroundSessionClaimReporter()
    # Ohne Mindestabstand prüft der zweite flush nur den Schutz gegen doppelte
    # Zustellung, nicht die Wartezeit.
    reporter.retry_spacing_seconds = 0.0
    machine, user = _machine_with_session(), _person()
    try:
        started = time.monotonic()
        assert reporter.report(machine, user, SHARED_ACCOUNT) == ""
        assert time.monotonic() - started < 0.5
        assert len(reporter.pending) == 1

        reporter.flush([machine], user)
        release.set()
        qtbot.waitUntil(lambda: reporter.pending == [], timeout=3000)
        assert len(calls) == 1
    finally:
        release.set()
        reporter.stop()


def test_a_failed_report_stays_pending_and_waits_before_retrying(
    monkeypatch, qtbot
) -> None:
    calls: list[str] = []

    def broken_pipe(target, claim, pipe_name=None, credentials=None):
        calls.append(target)
        raise OSError("Agent nicht erreichbar")

    monkeypatch.setattr(session_claims, "push_session_claim", broken_pipe)
    reporter = BackgroundSessionClaimReporter()
    machine, user = _machine_with_session(), _person()
    try:
        reporter.report(machine, user, SHARED_ACCOUNT)
        qtbot.waitUntil(lambda: reporter.pending[0].last_error != "", timeout=3000)

        reporter.flush([machine], user)
        assert len(calls) == 1, "innerhalb des Mindestabstands erneut zugestellt"

        reporter.pending[0].last_attempt_at -= reporter.retry_spacing_seconds + 1
        reporter.flush([machine], user)
        qtbot.waitUntil(lambda: len(calls) == 2, timeout=3000)
        assert len(reporter.pending) == 1
    finally:
        reporter.stop()


# --- Offene RDP-Fenster ------------------------------------------------------


class _FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid

    def poll(self):
        return None


def test_open_window_check_reuses_the_last_enumeration(tmp_path, monkeypatch) -> None:
    enumerations: list[list[int]] = []

    def fake_windows(pids):
        enumerations.append(list(pids))
        return [1]

    monkeypatch.setattr("portal_app.rdp.window_focus.windows_of_processes", fake_windows)
    processes = [_FakeProcess(4711), _FakeProcess(4712)]
    monkeypatch.setattr(
        "portal_app.rdp.launcher.subprocess.Popen",
        lambda *args, **kwargs: processes.pop(0),
    )
    launcher = RDPSessionLauncher(RDPFileGenerator(str(tmp_path)))
    monkeypatch.setattr(launcher, "_find_mstsc", lambda: "mstsc.exe")
    first = Workstation("WS-FIRST", "Erste Maschine", "pc-first")
    second = Workstation("WS-SECOND", "Zweite Maschine", "pc-second")

    launcher.launch(first.get_rdp_profile(), first.workstation_id, first.display_name)
    for _ in range(5):
        assert launcher.has_active_session("WS-FIRST")
    assert len(enumerations) == 1

    # Ein Start verwirft das gemerkte Ergebnis sofort.
    launcher.launch(second.get_rdp_profile(), second.workstation_id, second.display_name)
    assert launcher.has_active_session("WS-SECOND")
    assert len(enumerations) == 3  # eine Aufzählung je laufendem Prozess

    # Nach Ablauf der Frist wird neu gezählt.
    monkeypatch.setattr(launcher_module, "ACTIVE_SESSION_CACHE_SECONDS", 0.0)
    launcher.has_active_session("WS-FIRST")
    assert len(enumerations) == 5


# --- Live-Antworten im Hauptfenster ------------------------------------------


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    store = LocalStore(tmp_path / "state.json")
    store.save([Workstation("WS-1", "WS-1", "WS-1")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    created = MainWindow(automatic_live_status=False)
    qtbot.addWidget(created)
    yield created
    created.fallback_scanner.stop()
    created._claim_reporter.stop()


def test_live_answers_read_no_folder_and_are_applied_once(
    window, monkeypatch, qtbot
) -> None:
    scans: list[object] = []
    monkeypatch.setattr(
        LocalAgentStatusService,
        "scan_directories",
        staticmethod(lambda directories: scans.append(directories) or {}),
    )
    requested: list[object] = []
    monkeypatch.setattr(
        window.fallback_scanner,
        "request",
        lambda directories: requested.append(directories) or True,
    )
    applied: list[object] = []
    original = window._apply_fallback_scans
    monkeypatch.setattr(
        window,
        "_apply_fallback_scans",
        lambda result, changed: applied.append(result) or original(result, changed),
    )
    machine = window.workstations[0]
    route = machine.get_agent_status_target()

    for _ in range(3):
        window._on_live_status_succeeded(
            "WS-1", route, AgentSnapshot("WS-1", "WS-1", "1.3.0"), 12
        )

    assert scans == [], "eine Live-Antwort las die Fallbackordner im UI-Thread"
    assert requested == []
    qtbot.waitUntil(lambda: len(applied) == 1, timeout=2000)
    qtbot.wait(300)
    assert len(applied) == 1, "die Antworten eines Laufs wurden nicht gebündelt"
    assert machine.agent_status_source == "live"


# --- Namensauflösung ---------------------------------------------------------


@pytest.fixture
def fresh_names():
    name_resolution.clear_cache()
    yield
    name_resolution.clear_cache()


def test_an_expired_answer_is_used_while_a_new_lookup_runs(
    fresh_names, monkeypatch, qtbot
) -> None:
    release = threading.Event()
    calls: list[str] = []

    def slow_lookup(name):
        calls.append(name)
        release.wait(timeout=5)
        return True

    monkeypatch.setattr(name_resolution, "_lookup", slow_lookup)
    name_resolution.remember("PC07", False, now=0.0)
    try:
        started = time.monotonic()
        # Die negative Antwort ist abgelaufen. Früher wartete das hier auf DNS.
        assert name_resolution.resolvable("PC07") is False
        assert name_resolution.resolvable("PC07") is False
        assert time.monotonic() - started < 0.5
        assert calls == ["PC07"], "eine zweite Auffrischung wurde gestartet"
    finally:
        release.set()
    qtbot.waitUntil(lambda: name_resolution.resolvable("PC07"), timeout=3000)


# --- Wachhund ----------------------------------------------------------------


def test_a_blocked_ui_thread_is_logged_with_its_location(qtbot, caplog) -> None:
    watchdog = UiStallWatchdog(threshold_seconds=0.15)
    watchdog.start()
    try:
        qtbot.wait(100)

        def hold_the_ui_thread() -> None:
            time.sleep(0.4)

        with caplog.at_level("WARNING", logger="portal_app.ui.stall_watchdog"):
            hold_the_ui_thread()
            qtbot.waitUntil(
                lambda: any("war" in r.getMessage() for r in caplog.records),
                timeout=2000,
            )
        messages = [record.getMessage() for record in caplog.records]
        assert any("hold_the_ui_thread" in message for message in messages)
    finally:
        watchdog.stop()


def test_an_idle_ui_thread_logs_nothing(qtbot, caplog) -> None:
    watchdog = UiStallWatchdog(threshold_seconds=0.15)
    watchdog.start()
    try:
        with caplog.at_level("WARNING", logger="portal_app.ui.stall_watchdog"):
            qtbot.wait(500)
        assert caplog.records == []
    finally:
        watchdog.stop()


def test_a_new_name_waits_only_briefly_for_a_slow_dns(
    fresh_names, monkeypatch, qtbot
) -> None:
    release = threading.Event()

    def slow_lookup(name):
        release.wait(timeout=5)
        return True

    monkeypatch.setattr(name_resolution, "_lookup", slow_lookup)
    try:
        started = time.monotonic()
        assert name_resolution.resolvable("PC07") is False
        elapsed = time.monotonic() - started
        assert elapsed < name_resolution.COLD_WAIT_SECONDS + 0.3
        # Solange die Abfrage läuft, wartet kein weiterer Aufruf mehr.
        started = time.monotonic()
        assert name_resolution.resolvable("PC07") is False
        assert time.monotonic() - started < 0.05
    finally:
        release.set()
    # Die Abfrage läuft weiter und füllt den Cache.
    qtbot.waitUntil(lambda: name_resolution.resolvable("PC07"), timeout=3000)


def test_a_fast_dns_answer_is_used_right_away(fresh_names, monkeypatch) -> None:
    monkeypatch.setattr(name_resolution, "_lookup", lambda name: True)
    assert name_resolution.resolvable("PC07") is True


def test_prefetched_names_are_looked_up_side_by_side(
    fresh_names, monkeypatch
) -> None:
    def slow_lookup(name):
        time.sleep(0.5)
        return True

    monkeypatch.setattr(name_resolution, "_lookup", slow_lookup)
    names = ["PC01", "PC02", "PC03", "PC04"]
    name_resolution.prefetch(names + ["192.168.2.10", "", None])
    time.sleep(0.8)  # einmal 0,5 s, nicht viermal

    started = time.monotonic()
    assert all(name_resolution.resolvable(name) for name in names)
    assert time.monotonic() - started < 0.1


def test_the_prefetch_list_covers_the_share_server() -> None:
    machine = Workstation("WS-1", "PC07", "PC07", fqdn="pc07.kirschke.local")
    machine.agent_fallback_directory = r"\\FILESRV\RDP-Status"
    machine.agent_fallback_is_explicit = True
    assert machine.names_to_resolve() == ["pc07.kirschke.local", "PC07", "FILESRV"]
