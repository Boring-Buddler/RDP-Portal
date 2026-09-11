from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLineEdit

from portal_app.models.workstation import Workstation
from portal_app.models.user import MockUser
from portal_app.services.session_control import logoff_admin_session, logoff_own_session
from portal_app.ui.widgets.workstation_cards import WorkstationCard
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog
from shared.agent_snapshot import AgentSnapshot
from shared.enums import SessionState, ManualFlagType
from workstation_agent.session_control import AgentSessionController


def machine(state=SessionState.DISCONNECTED):
    return Workstation("A", "Desktop", "REMOTE", current_session_state=state,
                       current_session_user="AzureAD\\tester", selected_login_account="AzureAD\\tester",
                       login_accounts=["AzureAD\\tester"], agent_sessions=[dict(session_id=3, username="tester",
                       domain="AzureAD", session_state=state.value, login_time="2026-09-10T08:00:00+00:00")])


@pytest.mark.parametrize("state", [SessionState.CONNECTED, SessionState.DISCONNECTED, SessionState.RECONNECTED, SessionState.LOGON])
def test_reconnect_requires_matching_account(state):
    ws = machine(state)
    assert ws.can_connect()
    ws.selected_login_account = "azuread\\TESTER"
    assert ws.can_connect()
    for other in ("OTHER\\tester", "tester", "tester@example.com", "AzureAD\\someone"):
        ws.selected_login_account = other
        assert not ws.can_connect()
    ws.selected_login_account = None
    assert not ws.can_connect()
    assert ws.can_connect("AzureAD\\tester")
    ws.manual_flag_type = ManualFlagType.MAINTENANCE
    assert not ws.can_connect("AzureAD\\tester")


def test_detail_actions_follow_account(qtbot):
    user = MockUser.create_user()
    user.windows_identity = "AzureAD\\tester"
    detail = WorkstationDetailWidget(user)
    qtbot.addWidget(detail)
    ws = machine()
    detail.set_workstation(ws)
    assert detail.connect_btn.isEnabled()
    assert detail.connect_btn.text() == "Wiederverbinden"
    assert detail.logoff_btn.isEnabled()
    ws.selected_login_account = "OTHER\\tester"
    detail.set_workstation(ws)
    assert detail.connect_btn.isEnabled()
    assert detail.connect_btn.text() == "Wiederverbinden"
    assert detail.logoff_btn.isEnabled()


def test_card_primary_actions_distinguish_connected_disconnected_and_foreign(qtbot):
    user = MockUser.create_user()
    user.rdp_domain = "AzureAD"
    user.rdp_username = "tester"
    user.windows_identity = "AzureAD\\tester"
    connected = machine(SessionState.CONNECTED)
    card = WorkstationCard(connected, user)
    qtbot.addWidget(card)
    assert card.connect_btn.isHidden()
    assert not card.logoff_btn.isHidden()
    assert card.logoff_btn.objectName() == "dangerButton"

    disconnected = machine(SessionState.DISCONNECTED)
    card.set_workstation(disconnected, user)
    assert not card.connect_btn.isHidden()
    assert card.connect_btn.text() == "Wiederverbinden"
    assert not card.logoff_btn.isHidden()

    disconnected.selected_login_account = "AzureAD\\other"
    card.set_workstation(disconnected, user)
    assert not card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Wiederverbinden"

    user.windows_identity = "AzureAD\\other"
    user.rdp_username = None
    user.rdp_domain = None
    disconnected.selected_login_account = None
    disconnected.username_hint = None
    card.set_workstation(disconnected, user)
    assert card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Sitzung öffnen …"

    disconnected.selected_login_account = "AzureAD\\tester"
    disconnected.reservation_block_reason = "Fremd reserviert"
    disconnected.reservation_message = "Reserviert für eine andere Person"
    card.set_workstation(disconnected, user)
    assert card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Reserviert"


def test_disconnected_own_session_uses_process_identity_not_empty_rdp_default(qtbot):
    user = MockUser.create_user()
    user.rdp_username = None
    user.rdp_domain = None
    user.windows_identity = "AzureAD\\tester"
    workstation = machine(SessionState.DISCONNECTED)
    workstation.selected_login_account = None
    workstation.username_hint = None
    card = WorkstationCard(workstation, user)
    qtbot.addWidget(card)

    assert card.connect_btn.text() == "Wiederverbinden"
    assert not card.logoff_btn.isHidden()


@pytest.fixture
def native(monkeypatch):
    import win32security
    import portal_app.services.session_control as session_control
    session = dict(
        session_id=3,
        username="tester",
        domain="AzureAD",
        session_state="disconnected",
        login_time="2026-09-10T08:00:00+00:00",
    )
    snapshot = AgentSnapshot(
        "A",
        "REMOTE",
        "1.2.1",
        rdp_sessions=[session],
    )
    ended = AgentSnapshot("A", "REMOTE", "1.2.1", rdp_sessions=[])
    request = Mock(side_effect=[(snapshot, 2), (snapshot, 2), (ended, 2)])
    monkeypatch.setattr(
        "portal_app.services.session_control.request_snapshot",
        request,
    )
    lookup = Mock(return_value=("same-sid", "AzureAD", 1))
    monkeypatch.setattr(win32security, "LookupAccountName", lookup)
    token = Mock()
    monkeypatch.setattr(win32security, "OpenProcessToken", Mock(return_value=token))
    monkeypatch.setattr(win32security, "GetTokenInformation", Mock(return_value=("same-sid", 0)))
    agent_logoff = Mock(return_value="abgemeldet")
    monkeypatch.setattr(session_control, "request_agent_logoff", agent_logoff)
    return SimpleNamespace(snapshot=snapshot, session=session, request=request,
                           lookup=lookup, agent_logoff=agent_logoff, token=token)


def call_logoff():
    logoff_own_session(
        "REMOTE",
        3,
        "AzureAD\\tester",
        "2026-09-10T08:00:00+00:00",
        "A",
    )


def test_logoff_checks_live_session_and_windows_sid(native):
    call_logoff()
    assert native.request.call_count == 3
    native.lookup.assert_called_once_with(None, "AzureAD\\tester")
    native.agent_logoff.assert_called_once()
    assert native.agent_logoff.call_args.args[:2] == ("REMOTE", 3)
    native.token.Close.assert_called_once()


def test_admin_logoff_rechecks_identity_but_relies_on_windows_rights(native):
    logoff_admin_session("REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A")
    assert native.request.call_count == 3
    native.agent_logoff.assert_called_once()
    native.lookup.assert_not_called()
    native.token.Close.assert_not_called()


def test_logoff_checks_smb_status_host_but_sends_wts_request_to_rdp_ip(native):
    logoff_own_session(
        "192.168.2.10",
        3,
        "AzureAD\\tester",
        "2026-09-10T08:00:00+00:00",
        "A",
        "Remote-Ettlingen",
    )

    assert [call.args[0] for call in native.request.call_args_list] == [
        "Remote-Ettlingen",
        "Remote-Ettlingen",
        "Remote-Ettlingen",
    ]
    assert native.agent_logoff.call_args.args[:2] == ("Remote-Ettlingen", 3)


def test_no_logoff_of_another_windows_identity(native):
    native.lookup.return_value = ("other-sid", "AzureAD", 1)
    with pytest.raises(ValueError, match="Windows-Konto"):
        call_logoff()
    native.agent_logoff.assert_not_called()


def test_recycled_session_id_is_rejected(native):
    native.session["login_time"] = "2026-09-10T09:00:00+00:00"
    with pytest.raises(ValueError, match="Anmeldezeitpunkt"):
        call_logoff()
    native.agent_logoff.assert_not_called()


def test_session_changes_during_authorization(native):
    changed = AgentSnapshot(
        "A",
        "REMOTE",
        "1.2.1",
        rdp_sessions=[dict(native.session, username="other")],
    )
    native.request.side_effect = [(native.snapshot, 2), (changed, 2)]
    with pytest.raises(ValueError, match="Benutzer"):
        call_logoff()
    native.agent_logoff.assert_not_called()


def test_windows_denial_is_reported_without_native_call_in_portal(native):
    native.agent_logoff.side_effect = PermissionError("Windows-Administrator fehlt")
    with pytest.raises(PermissionError, match="Administrator"):
        call_logoff()
    assert native.request.call_count == 2


def test_logoff_is_not_reported_until_agent_confirms_end(native):
    native.request.side_effect = [
        (native.snapshot, 2),
        (native.snapshot, 2),
        (native.snapshot, 2),
    ]
    with pytest.raises(RuntimeError, match="weiterhin als aktiv"):
        call_logoff()


def test_isolated_helper_waits_for_logoff_and_closes_handle(monkeypatch):
    import win32ts
    from portal_app.session_logoff_helper import request_logoff

    handle = Mock()
    open_server = Mock(return_value=handle)
    logoff = Mock()
    monkeypatch.setattr(win32ts, "WTSOpenServer", open_server)
    monkeypatch.setattr(win32ts, "WTSLogoffSession", logoff)
    close_server = Mock(side_effect=AssertionError("must not bypass PyTS_HANDLE.Close"))
    monkeypatch.setattr(win32ts, "WTSCloseServer", close_server)

    request_logoff("REMOTE", 3)

    open_server.assert_called_once_with("REMOTE")
    logoff.assert_called_once_with(handle, 3, True)
    handle.Close.assert_called_once_with()
    close_server.assert_not_called()


def test_isolated_helper_closes_handle_after_logoff_error(monkeypatch):
    import win32ts
    from portal_app.session_logoff_helper import request_logoff

    handle = Mock()
    monkeypatch.setattr(win32ts, "WTSOpenServer", Mock(return_value=handle))
    monkeypatch.setattr(
        win32ts,
        "WTSLogoffSession",
        Mock(side_effect=OSError(5, "access denied")),
    )

    with pytest.raises(OSError):
        request_logoff("REMOTE", 3)

    handle.Close.assert_called_once_with()


def agent_command(**changes):
    command = {
        "protocol": "LOGOFF/1",
        "request_id": "request-1234567890",
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": 3,
        "username": "AzureAD\\tester",
        "login_time": "2026-09-10T08:00:00+00:00",
        "requester_identity": "AzureAD\\tester",
        "expected_agent_id": "A",
        "administrative": False,
    }
    command.update(changes)
    return command


@pytest.fixture
def agent_controller(monkeypatch):
    session = SimpleNamespace(
        session_id=3,
        full_username="AzureAD\\tester",
        login_time=datetime(2026, 9, 10, 8, tzinfo=timezone.utc),
        session_state=SessionState.CONNECTED,
        is_rdp_session=True,
        client_name="PC12",
    )
    monitor = Mock()
    monitor.__enter__ = Mock(return_value=monitor)
    monitor.__exit__ = Mock(return_value=False)
    monitor.get_user_sessions.return_value = [session]
    monkeypatch.setattr("workstation_agent.session_control.WTSMonitor", Mock(return_value=monitor))
    after = Mock()
    return AgentSessionController("A", after), monitor, after


def test_agent_logs_off_exact_owner_session_from_reported_rdp_client(agent_controller):
    controller, monitor, after = agent_controller
    result = controller.handle(agent_command(), "PC12.example", False)
    assert result["ok"] is True
    monitor.logoff_session.assert_called_once_with(3, wait=True)
    after.assert_called_once_with()


def test_agent_rejects_owner_from_another_client_or_with_replayed_request(agent_controller):
    controller, monitor, _ = agent_controller
    with pytest.raises(PermissionError, match="RDP-Client"):
        controller.handle(agent_command(), "OTHER-PC", False)
    monitor.logoff_session.assert_not_called()
    with pytest.raises(PermissionError, match="bereits verarbeitet"):
        controller.handle(agent_command(), "PC12", False)


def test_agent_requires_target_windows_admin_for_administrative_logoff(agent_controller):
    controller, monitor, _ = agent_controller
    command = agent_command(
        request_id="admin-request-12345",
        requester_identity="OTHER\\admin",
        administrative=True,
    )
    with pytest.raises(PermissionError, match="kein Administrator"):
        controller.handle(command, "ADMIN-PC", False)
    monitor.logoff_session.assert_not_called()

    command["request_id"] = "admin-request-67890"
    result = controller.handle(command, "ADMIN-PC", True)
    assert result["ok"] is True
    monitor.logoff_session.assert_called_once_with(3, wait=True)


def test_agent_rejects_stale_or_wrong_target_command(agent_controller):
    controller, monitor, _ = agent_controller
    stale = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    with pytest.raises(PermissionError, match="nicht mehr aktuell"):
        controller.handle(agent_command(requested_at_utc=stale), "PC12", False)
    with pytest.raises(PermissionError, match="Agent-ID"):
        controller.handle(agent_command(request_id="request-0987654321", expected_agent_id="B"), "PC12", False)
    monitor.logoff_session.assert_not_called()


def test_admin_logoff_dialog_requires_target_credentials(qtbot):
    dialog = SessionLogoffDialog(
        "REMOTE",
        "Remote",
        {
            "session_id": 3,
            "username": "tester",
            "domain": "AzureAD",
            "login_time": "2026-09-10T08:00:00+00:00",
        },
        administrative=True,
        expected_agent_id="A",
        status_target="REMOTE",
    )
    qtbot.addWidget(dialog)
    dialog._start()
    assert dialog.worker is None
    assert "Administrator-Anmeldedaten" in dialog.status.text()
    assert dialog.admin_password.echoMode() == QLineEdit.Password


def test_main_window_reconnect_reaches_launcher_with_session_account(monkeypatch):
    import portal_app.rdp as rdp
    import portal_app.ui.main_window as module
    ws = machine()
    ws.trust_unverified_server = True
    window = SimpleNamespace(current_user=MockUser.create_user(), _record_event=Mock(), _poll_rdp_sessions=Mock(),
                             _check_reservation_access=Mock(return_value=True))
    launcher = Mock(return_value=(True, "started"))
    monkeypatch.setattr(rdp, "has_active_rdp_session", Mock(return_value=False))
    monkeypatch.setattr(rdp, "launch_rdp_session", launcher)
    monkeypatch.setattr(module.QMessageBox, "information", Mock())
    monkeypatch.setattr(module.QMessageBox, "warning", Mock())
    monkeypatch.setattr(module.QInputDialog, "getItem", Mock(return_value=("", False)))
    module.MainWindow.on_connect_requested(window, ws)
    assert launcher.call_count == 1
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"
    launcher.reset_mock()
    ws.selected_login_account = "OTHER\\tester"
    chooser = Mock(return_value=("", False))
    monkeypatch.setattr(module.QInputDialog, "getItem", chooser)
    window._refresh_login_views = Mock()
    module.MainWindow.on_connect_requested(window, ws)
    chooser.assert_not_called()
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"


def test_main_window_reconnect_asks_only_when_multiple_sessions(monkeypatch):
    import portal_app.rdp as rdp
    import portal_app.ui.main_window as module

    ws = machine()
    ws.trust_unverified_server = True
    ws.selected_login_account = "OTHER\\tester"
    ws.agent_sessions.append(dict(ws.agent_sessions[0], session_id=4, username="other",
                                  full_username="AzureAD\\other"))
    window = SimpleNamespace(current_user=MockUser.create_user(), _record_event=Mock(),
                             _poll_rdp_sessions=Mock(), _refresh_login_views=Mock(),
                             _check_reservation_access=Mock(return_value=True))
    launcher = Mock(return_value=(True, "started"))
    chooser = Mock(return_value=("AzureAD\\tester", True))
    monkeypatch.setattr(rdp, "has_active_rdp_session", Mock(return_value=False))
    monkeypatch.setattr(rdp, "launch_rdp_session", launcher)
    monkeypatch.setattr(module.QMessageBox, "information", Mock())
    monkeypatch.setattr(module.QMessageBox, "warning", Mock())
    monkeypatch.setattr(module.QInputDialog, "getItem", chooser)

    module.MainWindow.on_connect_requested(window, ws)

    chooser.assert_called_once()
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"
