from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import uuid

import pytest

from portal_app.models.reservation import Reservation
from portal_app.models.workstation import Workstation
from portal_app.models.user import MockUser
from portal_app.services.reservation_access import apply_reservations
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.local_store import LocalStore, StoreConflictError
from shared.agent_snapshot import AgentSnapshot, write_agent_snapshot
from shared.enums import SessionState


def test_reservation_boundaries_and_identity():
    start = datetime(2026, 9, 10, 9)
    end = start + timedelta(hours=1)
    r = Reservation('A', 'Arbeit', start, end, 'owner@example.com')
    ws = Workstation('A', 'A', 'PC')
    apply_reservations([ws], [r], 'other@example.com', start - timedelta(seconds=1))
    assert ws.can_connect()
    apply_reservations([ws], [r], 'other@example.com', start)
    assert not ws.can_connect()
    assert 'owner@example.com' in ws.reservation_message
    apply_reservations([ws], [r], 'OWNER@example.com', start)
    assert ws.can_connect()
    ws.current_session_state = SessionState.DISCONNECTED
    ws.current_session_user = 'AzureAD\\Owner'
    ws.selected_login_account = 'AzureAD\\Owner'
    assert ws.can_connect()
    apply_reservations([ws], [r], 'other@example.com', start)
    assert not ws.can_connect() and not ws.can_choose_session()
    apply_reservations([ws], [r], 'other@example.com', end)
    assert ws.can_connect()


def test_owner_cannot_implicitly_take_foreign_windows_session():
    now = datetime.now()
    ws = Workstation('A', 'A', 'PC', current_session_state=SessionState.CONNECTED,
                     current_session_user='PC\\other', selected_login_account='PC\\owner')
    apply_reservations([ws], [Reservation('A', 'Work', now, now+timedelta(hours=1), 'owner')], 'owner', now)
    assert not ws.can_connect()


def test_parallel_reservation_conflict_and_fresh_read(tmp_path):
    a = LocalStore(tmp_path/'state.json')
    user = MockUser.create_user()
    ws = Workstation('A', 'A', 'PC')
    a.save([ws], user, [])
    b = LocalStore(a.path)
    b.load([], user)
    now = datetime.now()
    first = Reservation('A', 'first', now, now+timedelta(hours=1), 'owner')
    a.save([ws], user, [first])
    assert b.read_reservations()[0].reserved_by == 'owner'
    with pytest.raises(StoreConflictError):
        b.save([ws], user, [Reservation('A', 'second', now, now+timedelta(hours=1), 'other')])


def test_admin_edit_preserves_reservation_owner(qtbot):
    from portal_app.ui.widgets.reservation_calendar import ReservationDialog
    now = datetime.now()
    user = MockUser.create_admin()
    r = Reservation('A', 'first', now, now+timedelta(hours=1), 'original@example.com')
    dialog = ReservationDialog([Workstation('A', 'A', 'PC')], user, reservation=r)
    qtbot.addWidget(dialog)
    dialog._accept()
    assert dialog.reservation.reserved_by == r.reserved_by


def test_newer_live_snapshot_survives_old_json(tmp_path):
    ws = Workstation('A', 'A', 'PC')
    service = LocalAgentStatusService(directory=tmp_path)
    now = datetime.now(timezone.utc)
    write_agent_snapshot(AgentSnapshot('A', 'PC', '1', observed_at_utc=now-timedelta(seconds=30),
                         current_session_state=SessionState.DISCONNECTED), tmp_path)
    live = AgentSnapshot('A', 'PC', '1.2.0', observed_at_utc=now, current_session_state=SessionState.CONNECTED)
    service.accept_live_snapshot(ws, live, 4)
    service.apply([ws])
    assert ws.current_session_state == SessionState.CONNECTED
    assert 'Live-Abfrage' in ws.agent_diagnostic
    write_agent_snapshot(AgentSnapshot('A', 'PC', '1.2.0', observed_at_utc=now+timedelta(seconds=1)), tmp_path)
    service.apply([ws])
    assert ws.current_session_state == SessionState.NONE
    assert 'Live-Abfrage' not in ws.agent_diagnostic
    with pytest.raises(ValueError):
        service.accept_live_snapshot(ws, AgentSnapshot('B', 'WRONG', '1.2.0'), 4)


def test_native_status_pipe_roundtrip_idle_and_rejected_command():
    import time
    import win32api
    import win32file
    import win32pipe
    import win32con
    from workstation_agent.status_server import StatusServer
    from shared.status_pipe import request_snapshot, CLIENT_ACCESS, write_message
    name = 'KirschkeTest-' + uuid.uuid4().hex
    factory = Mock(return_value=AgentSnapshot('TEST', win32api.GetComputerName(), '1.2.0'))
    server = StatusServer(factory, win32api.GetUserName(), name)
    server.start()
    assert server.ready.wait(3) and server.error is None
    try:
        for _ in range(2):
            snapshot, elapsed = request_snapshot(win32api.GetComputerName(), name)
            assert snapshot.workstation_id == 'TEST' and elapsed >= 0
            time.sleep(1.2)  # Exercises canceled idle accept and the next connection.
        assert factory.call_count == 2
        path = rf'\\.\pipe\{name}'
        win32pipe.WaitNamedPipe(path, 1500)
        h = win32file.CreateFile(path, CLIENT_ACCESS, 0, None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED, None)
        try:
            write_message(h, b'LOGOFF 3')
        finally:
            h.Close()
        time.sleep(.1)
        assert factory.call_count == 2
    finally:
        server.stop()
    assert not server.is_alive() and server.error is None


def test_pipe_reader_cannot_create_server_instance():
    from shared.status_pipe import CLIENT_ACCESS
    from workstation_agent.status_server import security_attributes
    import win32api
    acl = security_attributes(win32api.GetUserName()).SECURITY_DESCRIPTOR.GetSecurityDescriptorDacl()
    assert acl.GetAceCount() == 3
    assert acl.GetAce(2)[1] == CLIENT_ACCESS
    assert CLIENT_ACCESS & 4 == 0


@pytest.mark.parametrize('field,value', [('domain', 123), ('username', []), ('full_username', {}),
                                      ('session_id', True), ('session_state', 'unknown')])
def test_malformed_session_cannot_crash_account_selector(field, value):
    data = AgentSnapshot('A', 'PC', '1.2.0', rdp_sessions=[{field: value}]).to_dict()
    with pytest.raises(ValueError):
        AgentSnapshot.from_dict(data)
