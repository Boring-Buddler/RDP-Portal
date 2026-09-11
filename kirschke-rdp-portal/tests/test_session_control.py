from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from portal_app.models.workstation import Workstation
from portal_app.models.user import MockUser
from portal_app.services.session_control import logoff_own_session
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from shared.enums import SessionState, ManualFlagType


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
    detail = WorkstationDetailWidget(MockUser.create_user())
    qtbot.addWidget(detail)
    ws = machine()
    detail.set_workstation(ws)
    assert detail.connect_btn.isEnabled()
    assert detail.connect_btn.text() == "Wiederverbinden"
    assert detail.logoff_btn.isEnabled()
    ws.selected_login_account = "OTHER\\tester"
    detail.set_workstation(ws)
    assert detail.connect_btn.isEnabled()
    assert detail.connect_btn.text() == "Sitzung öffnen …"
    assert not detail.logoff_btn.isEnabled()


@pytest.fixture
def native(monkeypatch):
    import win32security
    import win32ts
    import workstation_agent.wts.monitor as module
    session = SimpleNamespace(full_username="AzureAD\\tester", login_time=datetime(2026, 9, 10, 8, tzinfo=timezone.utc))
    monitor = Mock()
    monitor.__enter__ = Mock(return_value=monitor)
    monitor.__exit__ = Mock(return_value=False)
    monitor.get_session.return_value = session
    monkeypatch.setattr(module, "WTSMonitor", Mock(return_value=monitor))
    lookup = Mock(return_value=("same-sid", "AzureAD", 1))
    monkeypatch.setattr(win32security, "LookupAccountName", lookup)
    token = Mock()
    monkeypatch.setattr(win32security, "OpenProcessToken", Mock(return_value=token))
    monkeypatch.setattr(win32security, "GetTokenInformation", Mock(return_value=("same-sid", 0)))
    monkeypatch.setattr(win32ts, "WTSOpenServer", Mock(return_value=123))
    close = Mock()
    logoff = Mock()
    monkeypatch.setattr(win32ts, "WTSCloseServer", close)
    monkeypatch.setattr(win32ts, "WTSLogoffSession", logoff)
    return SimpleNamespace(monitor=monitor, session=session, lookup=lookup, logoff=logoff, close=close, token=token)


def call_logoff():
    logoff_own_session("REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00")


def test_logoff_checks_live_session_and_windows_sid(native):
    call_logoff()
    assert native.monitor.get_session.call_count == 2
    native.logoff.assert_called_once_with(123, 3, False)
    native.close.assert_called_once_with(123)
    native.token.Close.assert_called_once()


def test_no_logoff_of_another_windows_identity(native):
    native.lookup.return_value = ("other-sid", "AzureAD", 1)
    with pytest.raises(ValueError, match="Windows-Konto"):
        call_logoff()
    native.logoff.assert_not_called()


def test_recycled_session_id_is_rejected(native):
    native.session.login_time = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="geändert"):
        call_logoff()
    native.logoff.assert_not_called()


def test_session_changes_during_authorization(native):
    native.monitor.get_session.side_effect = [native.session, SimpleNamespace(full_username="AzureAD\\other", login_time=native.session.login_time)]
    with pytest.raises(ValueError, match="geändert"):
        call_logoff()
    native.logoff.assert_not_called()
    native.close.assert_called_once()


def test_windows_denial_closes_handle(native):
    native.logoff.side_effect = OSError(5, "Access denied")
    with pytest.raises(OSError):
        call_logoff()
    native.close.assert_called_once()


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
    module.MainWindow.on_connect_requested(window, ws)
    launcher.assert_not_called()
    window._refresh_login_views = Mock()
    monkeypatch.setattr(module.QInputDialog, "getItem", Mock(return_value=("AzureAD\\tester", True)))
    module.MainWindow.on_connect_requested(window, ws)
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"
