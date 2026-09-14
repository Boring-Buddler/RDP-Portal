import uuid
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from unittest.mock import Mock

import pytest

from portal_app.models.reservation import Reservation
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.live_status_polling import AutomaticLiveStatusPoller
from portal_app.services.local_store import LocalStore, StoreConflictError
from portal_app.services.reservation_access import apply_reservations
from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot
from shared.enums import ConnectionTargetMode, SessionState


def test_reservation_boundaries_and_identity():
    start = datetime(2026, 9, 10, 9)
    end = start + timedelta(hours=1)
    r = Reservation("A", "Arbeit", start, end, "owner@example.com")
    ws = Workstation("A", "A", "PC")
    apply_reservations([ws], [r], "other@example.com", start - timedelta(seconds=1))
    assert ws.can_connect()
    apply_reservations([ws], [r], "other@example.com", start)
    assert not ws.can_connect()
    assert "owner@example.com" in ws.reservation_message
    apply_reservations([ws], [r], "OWNER@example.com", start)
    assert ws.can_connect()
    ws.current_session_state = SessionState.DISCONNECTED
    ws.current_session_user = "AzureAD\\Owner"
    ws.selected_login_account = "AzureAD\\Owner"
    assert ws.can_connect()
    apply_reservations([ws], [r], "other@example.com", start)
    assert not ws.can_connect() and not ws.can_choose_session()
    apply_reservations([ws], [r], "other@example.com", end)
    assert ws.can_connect()


def test_owner_cannot_implicitly_take_foreign_windows_session():
    now = datetime.now()
    ws = Workstation("A", "A", "PC", current_session_state=SessionState.CONNECTED,
                     current_session_user="PC\\other", selected_login_account="PC\\owner")
    apply_reservations([ws], [Reservation("A", "Work", now, now+timedelta(hours=1), "owner")], "owner", now)
    assert not ws.can_connect()


def test_parallel_reservation_conflict_and_fresh_read(tmp_path):
    a = LocalStore(tmp_path/"state.json")
    user = MockUser.create_user()
    ws = Workstation("A", "A", "PC")
    a.save([ws], user, [])
    b = LocalStore(a.path)
    b.load([], user)
    now = datetime.now()
    first = Reservation("A", "first", now, now+timedelta(hours=1), "owner")
    a.save([ws], user, [first])
    assert b.read_reservations()[0].reserved_by == "owner"
    with pytest.raises(StoreConflictError):
        b.save([ws], user, [Reservation("A", "second", now, now+timedelta(hours=1), "other")])


def test_admin_edit_preserves_reservation_owner(qtbot):
    from portal_app.ui.widgets.reservation_calendar import ReservationDialog
    now = datetime.now()
    user = MockUser.create_admin()
    r = Reservation("A", "first", now, now+timedelta(hours=1), "original@example.com")
    dialog = ReservationDialog([Workstation("A", "A", "PC")], user, reservation=r)
    qtbot.addWidget(dialog)
    dialog._accept()
    assert dialog.reservation.reserved_by == r.reserved_by


def test_newer_live_snapshot_survives_old_json(tmp_path):
    ws = Workstation("A", "A", "PC")
    service = LocalAgentStatusService(directory=tmp_path)
    now = datetime.now(UTC)
    write_agent_snapshot(AgentSnapshot("A", "PC", "1", observed_at_utc=now-timedelta(seconds=30),
                         current_session_state=SessionState.DISCONNECTED), tmp_path)
    live = AgentSnapshot("A", "PC", "1.2.0", observed_at_utc=now, current_session_state=SessionState.CONNECTED)
    service.accept_live_snapshot(ws, live, 4)
    service.apply([ws])
    assert ws.current_session_state == SessionState.CONNECTED
    assert "Live-Abfrage" in ws.agent_diagnostic
    assert ws.get_agent_source_display().startswith("Live ·")
    service.record_live_failure(ws, "Live-Abfrage fehlgeschlagen (53).")
    service.apply([ws])
    assert ws.current_session_state == SessionState.CONNECTED
    assert ws.get_agent_source_display().startswith("Live nicht erreichbar")
    write_agent_snapshot(AgentSnapshot("A", "PC", "1.2.0", observed_at_utc=now+timedelta(seconds=1)), tmp_path)
    service.apply([ws])
    assert ws.current_session_state == SessionState.NONE
    assert "Datei-Fallback" in ws.agent_diagnostic
    assert ws.get_agent_source_display().startswith("Datei-Fallback ·")
    service.accept_live_snapshot(
        ws,
        AgentSnapshot("A", "PC", "1.2.1", observed_at_utc=now+timedelta(seconds=2)),
        3,
    )
    service.apply([ws])
    assert ws.get_agent_source_display().startswith("Live ·")
    with pytest.raises(ValueError):
        service.accept_live_snapshot(ws, AgentSnapshot("B", "WRONG", "1.2.0"), 4)


def test_agent_status_reuses_explicit_smb_server_when_rdp_uses_ip():
    ws = Workstation(
        "A",
        "Remote",
        "Remote-Ettlingen",
        ip_address="192.168.2.10",
        connection_target_mode=ConnectionTargetMode.IP_ADDRESS,
        agent_fallback_directory=r"\\Remote-Ettlingen\RDP-Status",
        agent_fallback_is_explicit=True,
    )

    assert ws.get_connection_target()[0] == "192.168.2.10"
    assert ws.get_agent_status_target() == "Remote-Ettlingen"

    ws.agent_fallback_is_explicit = False
    assert ws.get_agent_status_target() == "192.168.2.10"


def test_automatic_live_poller_limits_overlap_and_backs_off(qtbot, monkeypatch):
    import portal_app.services.live_status_polling as module

    release = Event()
    both_started = Event()
    lock = Lock()
    active = 0
    maximum = 0
    calls = []

    def request(target):
        nonlocal active, maximum
        with lock:
            calls.append(target)
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                both_started.set()
        try:
            release.wait(1)
            if target == "SLOW":
                raise TimeoutError("bounded")
            return AgentSnapshot(target, target, "1.2.1"), 2
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(module, "request_snapshot", request)
    poller = AutomaticLiveStatusPoller(max_parallel=2)
    successes = []
    failures = []
    poller.succeeded.connect(lambda *args: successes.append(args))
    poller.failed.connect(lambda *args: failures.append(args))
    slow = Workstation("SLOW", "Slow", "SLOW")
    fast = Workstation("FAST", "Fast", "FAST")

    assert poller.request_many([slow, fast], 5) == 2
    assert poller.request_many([slow], 5) == 0
    qtbot.waitUntil(both_started.is_set)
    release.set()
    qtbot.waitUntil(lambda: len(successes) == 1)
    qtbot.waitUntil(lambda: len(failures) == 1 and not poller._in_flight)
    assert maximum == 2
    assert calls.count("SLOW") == 1
    assert poller.request_many([slow], 5) == 0
    assert poller.request_many([slow], 5, force=True) == 1
    qtbot.waitUntil(lambda: len(failures) == 2)
    poller.stop()


def test_native_status_pipe_roundtrip_idle_and_rejected_command():
    import time

    import win32api
    import win32con
    import win32file
    import win32pipe

    from shared.status_pipe import CLIENT_ACCESS, request_snapshot, write_message
    from workstation_agent.status_server import StatusServer
    name = "KirschkeTest-" + uuid.uuid4().hex
    factory = Mock(return_value=AgentSnapshot("TEST", win32api.GetComputerName(), "1.2.0"))
    server = StatusServer(factory, win32api.GetUserName(), name)
    server.start()
    assert server.ready.wait(3) and server.error is None
    try:
        for _ in range(2):
            snapshot, elapsed = request_snapshot(win32api.GetComputerName(), name)
            assert snapshot.workstation_id == "TEST" and elapsed >= 0
            time.sleep(1.2)  # Exercises canceled idle accept and the next connection.
        assert factory.call_count == 2
        path = rf"\\.\pipe\{name}"
        win32pipe.WaitNamedPipe(path, 1500)
        h = win32file.CreateFile(path, CLIENT_ACCESS, 0, None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED, None)
        try:
            write_message(h, b"LOGOFF 3")
        finally:
            h.Close()
        time.sleep(.1)
        assert factory.call_count == 2
    finally:
        server.stop()
    assert not server.is_alive() and server.error is None


def test_native_status_pipe_routes_bounded_logoff_request():
    import win32api

    from shared.status_pipe import request_agent_logoff
    from workstation_agent.status_server import StatusServer

    name = "KirschkeTest-" + uuid.uuid4().hex
    factory = Mock(return_value=AgentSnapshot("TEST", win32api.GetComputerName(), "1.2.3"))
    handler = Mock(return_value={"ok": True, "message": "verified"})
    server = StatusServer(factory, win32api.GetUserName(), name, handler)
    server.start()
    assert server.ready.wait(3) and server.error is None
    try:
        result = request_agent_logoff(
            win32api.GetComputerName(),
            3,
            "DOMAIN\\user",
            "2026-09-10T08:00:00+00:00",
            "DOMAIN\\user",
            "TEST",
            pipe_name=name,
        )
        assert result == "verified"
        command, client_name, is_admin = handler.call_args.args
        assert command["session_id"] == 3
        assert command["expected_agent_id"] == "TEST"
        assert client_name
        assert isinstance(is_admin, bool)
    finally:
        server.stop()


def test_pipe_reader_cannot_create_server_instance():
    import win32api

    from shared.status_pipe import CLIENT_ACCESS
    from workstation_agent.status_server import security_attributes
    acl = security_attributes(win32api.GetUserName()).SECURITY_DESCRIPTOR.GetSecurityDescriptorDacl()
    assert acl.GetAceCount() == 3
    assert acl.GetAce(2)[1] == CLIENT_ACCESS
    assert CLIENT_ACCESS & 4 == 0


@pytest.mark.parametrize("field,value", [("domain", 123), ("username", []), ("full_username", {}),
                                      ("session_id", True), ("session_state", "unknown")])
def test_malformed_session_cannot_crash_account_selector(field, value):
    data = AgentSnapshot("A", "PC", "1.2.0", rdp_sessions=[{field: value}]).to_dict()
    with pytest.raises(ValueError):
        AgentSnapshot.from_dict(data)
