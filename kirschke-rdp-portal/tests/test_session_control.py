from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLineEdit

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services import session_control
from portal_app.services.session_control import logoff_admin_session, logoff_own_session
from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog
from portal_app.ui.widgets.workstation_cards import WorkstationCard
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from shared.agent_snapshot import AgentSnapshot
from shared.enums import AgentStatus, ManualFlagType, SessionState
from workstation_agent.session_control import AgentSessionController


def machine(state=SessionState.DISCONNECTED):
    """Eine Maschine mit lebendem Agenten, damit der Sitzungszustand die Farbe bestimmt.

    Ohne aktuelle Agent-Meldung waere jede Maschine grau und "Status ungeprueft" --
    dann liessen sich die sitzungsabhaengigen Buttons gar nicht pruefen.
    """
    workstation = Workstation(
        "A", "Desktop", "REMOTE", current_session_state=state,
        agent_status=AgentStatus.ONLINE,
        current_session_user="AzureAD\\tester", selected_login_account="AzureAD\\tester",
        login_accounts=["AzureAD\\tester"], agent_sessions=[{"session_id": 3, "username": "tester",
        "domain": "AzureAD", "session_state": state.value, "login_time": "2026-09-10T08:00:00+00:00"}])
    workstation.agent_status_source = "live"
    return workstation


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
    assert detail.connect_btn.text() == "Sitzung öffnen"
    assert detail.logoff_btn.isEnabled()
    # Die Kontoauswahl ist eine Anzeigehilfe; Besitz kommt aus der Windows-Kennung
    # des Prozesses, also darf ein anderes gewaehltes Konto nichts veraendern.
    ws.selected_login_account = "OTHER\\tester"
    detail.set_workstation(ws)
    assert detail.connect_btn.isEnabled()
    assert detail.connect_btn.text() == "Sitzung öffnen"
    assert detail.logoff_btn.isEnabled()


def test_card_primary_actions_distinguish_connected_disconnected_and_foreign(qtbot):
    user = MockUser.create_user()
    user.rdp_domain = "AzureAD"
    user.rdp_username = "tester"
    user.windows_identity = "AzureAD\\tester"
    connected = machine(SessionState.CONNECTED)
    card = WorkstationCard(connected, user)
    qtbot.addWidget(card)
    # Eine eigene Sitzung hat den Primaerbutton frueher ganz ausgeblendet -- damit
    # stand man vor einer Maschine, auf der man angemeldet war, ohne Weg zurueck.
    assert not card.connect_btn.isHidden()
    assert card.connect_btn.text() == "Sitzung öffnen"
    assert card.connect_btn.isEnabled()
    assert not card.logoff_btn.isHidden()
    assert card.logoff_btn.isEnabled()
    assert card.logoff_btn.objectName() == "dangerButton"

    disconnected = machine(SessionState.DISCONNECTED)
    card.set_workstation(disconnected, user)
    assert not card.connect_btn.isHidden()
    assert card.connect_btn.text() == "Sitzung öffnen"
    assert not card.logoff_btn.isHidden()

    disconnected.selected_login_account = "AzureAD\\other"
    card.set_workstation(disconnected, user)
    assert not card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Sitzung öffnen"

    # Fremde Sitzung: besetzt, und kein Abmeldeweg.
    user.windows_identity = "AzureAD\\other"
    user.rdp_username = None
    user.rdp_domain = None
    disconnected.selected_login_account = None
    disconnected.username_hint = None
    card.set_workstation(disconnected, user)
    assert card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Maschine besetzt"
    assert not card.connect_btn.isEnabled()

    disconnected.selected_login_account = "AzureAD\\tester"
    disconnected.reservation_block_reason = "Fremd reserviert"
    disconnected.reservation_message = "Reserviert für eine andere Person"
    card.set_workstation(disconnected, user)
    assert card.logoff_btn.isHidden()
    assert card.connect_btn.text() == "Maschine besetzt"
    assert not card.connect_btn.isEnabled()


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

    assert card.connect_btn.text() == "Sitzung öffnen"
    assert not card.logoff_btn.isHidden()


@pytest.fixture
def native(monkeypatch):
    import win32security

    import portal_app.services.session_control as session_control
    session = {
        "session_id": 3,
        "username": "tester",
        "domain": "AzureAD",
        "session_state": "disconnected",
        "login_time": "2026-09-10T08:00:00+00:00",
    }
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
    monkeypatch.setattr(win32security, "ConvertSidToStringSid", lambda sid: str(sid))
    agent_logoff = Mock(return_value="abgemeldet")
    monkeypatch.setattr(session_control, "request_agent_logoff", agent_logoff)
    return SimpleNamespace(snapshot=snapshot, ended=ended, session=session, request=request,
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


def test_the_reported_sid_decides_and_no_name_is_resolved_locally(native):
    """The lookup this replaces is the one that fails for Entra accounts."""
    native.session["sid"] = "same-sid"

    call_logoff()

    native.lookup.assert_not_called()
    native.agent_logoff.assert_called_once()


def test_a_reported_sid_that_differs_stops_the_logoff(native):
    native.session["sid"] = "somebody-else"

    with pytest.raises(ValueError, match="Windows-Konto"):
        call_logoff()

    native.agent_logoff.assert_not_called()


def test_the_reported_sid_wins_over_a_name_that_would_have_matched(native):
    """A name that resolves to the caller must not rescue a foreign SID."""
    native.session["sid"] = "somebody-else"
    native.lookup.return_value = ("same-sid", "AzureAD", 1)

    with pytest.raises(ValueError, match="Windows-Konto"):
        call_logoff()

    native.agent_logoff.assert_not_called()


def test_a_claimed_account_passes_the_portal_check(native):
    """Eine Person mit zwei Windows-Konten soll ihre eigene Sitzung beenden koennen."""
    native.session["sid"] = "somebody-else"

    logoff_own_session(
        "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A",
        claimed_accounts=["AzureAD\\tester"],
    )

    native.agent_logoff.assert_called_once()


def test_a_claim_only_covers_the_accounts_actually_entered(native):
    native.session["sid"] = "somebody-else"

    with pytest.raises(ValueError, match="Windows-Konto"):
        logoff_own_session(
            "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A",
            claimed_accounts=["NB12KI\\Codex"],
        )

    native.agent_logoff.assert_not_called()


def test_without_a_claim_a_foreign_sid_still_stops_the_logoff(native):
    """Die Lockerung gilt nur, wenn jemand das Konto ausdruecklich eingetragen hat."""
    native.session["sid"] = "somebody-else"

    with pytest.raises(ValueError, match="Windows-Konto"):
        call_logoff()

    native.agent_logoff.assert_not_called()


def test_a_claim_does_not_reach_a_console_session(native):
    """Die Konsolenregel steht vor der Besitzpruefung und bleibt unberuehrt."""
    native.session["sid"] = "somebody-else"
    native.session["is_console_session"] = True

    with pytest.raises(ValueError, match="Konsolensitzung"):
        logoff_own_session(
            "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A",
            claimed_accounts=["AzureAD\\tester"],
        )

    native.agent_logoff.assert_not_called()


def test_a_claim_helps_when_the_agent_reports_no_sid_at_all(native):
    """Alter Agent plus eingetragenes Konto: die Namensaufloesung entfaellt."""
    logoff_own_session(
        "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A",
        claimed_accounts=["AzureAD\\tester"],
    )

    native.lookup.assert_not_called()
    native.agent_logoff.assert_called_once()


def test_a_console_session_is_refused_with_its_own_reason(native):
    """The agent would refuse too, but blame a mismatched RDP client for it."""
    native.session["is_console_session"] = True

    with pytest.raises(ValueError, match="Konsolensitzung"):
        call_logoff()

    native.agent_logoff.assert_not_called()


def test_an_admin_logoff_still_handles_a_console_session(native):
    """Windows admin rights on the target are proof; the console rule is not theirs."""
    native.session["is_console_session"] = True

    logoff_admin_session("REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A")

    native.agent_logoff.assert_called_once()


def test_a_missing_sid_and_an_unresolvable_name_say_why(native):
    native.lookup.side_effect = OSError(1332, "Keine Zuordnung")

    with pytest.raises(ValueError, match="Entra-Konten"):
        call_logoff()

    native.agent_logoff.assert_not_called()


def test_a_foreign_agent_names_both_ids_and_does_not_log_anything_off(native):
    """Eine Identitaetspruefung -- die Meldung muss sagen, was womit kollidiert."""
    native.snapshot.workstation_id = "B"
    native.snapshot.hostname = "ANDERER-PC"

    with pytest.raises(ValueError) as error:
        call_logoff()

    message = str(error.value)
    assert "Erwartet: A" in message
    assert "B" in message and "ANDERER-PC" in message
    assert "Agent zuordnen" in message
    native.agent_logoff.assert_not_called()


def test_admin_credentials_do_not_get_past_a_foreign_agent(native):
    """Adminrechte aendern nicht, welcher Rechner geantwortet hat."""
    native.snapshot.workstation_id = "B"

    with pytest.raises(ValueError, match="Identitätsprüfung"):
        logoff_admin_session(
            "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "A",
            admin_credentials=("ZIEL\\Administrator", "geheim"),
        )

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


def test_a_missing_agent_answer_is_checked_instead_of_reported_as_failure(native, monkeypatch):
    """Windows baut die Sitzung ab, bevor der Agent antwortet -- das ist kein Fehler.

    Genau dieser Fall meldete frueher "Fehler TimeoutError", obwohl die Sitzung
    beendet war.
    """
    monkeypatch.setattr("portal_app.services.session_control.time.sleep", lambda _s: None)
    native.agent_logoff.side_effect = TimeoutError("Keine rechtzeitige Antwort vom Agenten.")

    call_logoff()

    assert native.request.call_count == 3


def test_a_missing_answer_on_a_surviving_session_says_it_was_not_confirmed(native, monkeypatch):
    monkeypatch.setattr("portal_app.services.session_control.time.sleep", lambda _s: None)
    native.agent_logoff.side_effect = TimeoutError("Keine rechtzeitige Antwort vom Agenten.")
    native.request.side_effect = [(native.snapshot, 2)] * 12

    with pytest.raises(RuntimeError, match="nicht rechtzeitig beantwortet"):
        call_logoff()

    assert native.request.call_count == 2 + session_control.UNANSWERED_CONFIRM_ATTEMPTS


def test_the_logoff_request_waits_longer_than_a_status_query(monkeypatch):
    """WTSLogoffSession laeuft mit bWait=TRUE, die Antwort kommt erst danach."""
    import shared.status_pipe as status_pipe

    exchange = Mock(return_value={"ok": True, "message": "abgemeldet"})
    monkeypatch.setattr(status_pipe, "_exchange", exchange)

    status_pipe.request_agent_logoff(
        "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "AzureAD\\tester", "A"
    )

    assert exchange.call_args.kwargs["response_timeout_ms"] == status_pipe.LOGOFF_TIMEOUT_MS
    assert status_pipe.LOGOFF_TIMEOUT_MS > status_pipe.DEFAULT_TIMEOUT_MS


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
        "requested_at_utc": datetime.now(UTC).isoformat(),
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
        login_time=datetime(2026, 9, 10, 8, tzinfo=UTC),
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
    with pytest.raises(PermissionError, match="Anfrage kam von: OTHER-PC"):
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
    stale = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
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
    # Ein erfolgreicher Start merkt sich jetzt das benutzte Konto, deshalb braucht
    # der Stub die Speicher- und Auffrischwege.
    window = SimpleNamespace(current_user=MockUser.create_user(), _record_event=Mock(), _poll_rdp_sessions=Mock(),
                             _check_reservation_access=Mock(return_value=True),
                             _persist=Mock(), _refresh_workstation_views=Mock(), _saved_user=None)
    launcher = Mock(return_value=(True, "started"))
    monkeypatch.setattr(rdp, "has_active_rdp_session", Mock(return_value=False))
    monkeypatch.setattr(rdp, "launch_rdp_session", launcher)
    monkeypatch.setattr(module.QMessageBox, "information", Mock())
    monkeypatch.setattr(module.QMessageBox, "warning", Mock())
    monkeypatch.setattr(module.QInputDialog, "getItem", Mock(return_value=("", False)))
    module.MainWindow.on_connect_requested(window, ws)
    assert launcher.call_count == 1
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"
    # Das Konto, mit dem verbunden wurde, gilt danach als eigenes.
    assert window.current_user.own_accounts == ["AzureAD\\tester"]
    window._persist.assert_called_once()
    launcher.reset_mock()
    # Zweiter Teil: die Sitzung gehoert dem Portal-Benutzer *nicht*. Dann korrigiert
    # das Portal ein unpassend gewaehltes Konto auf das einzige gemeldete
    # Sitzungskonto -- ohne zu fragen, weil es nichts zu waehlen gibt. Das im ersten
    # Teil gelernte Konto muss dafuer weg, sonst waere die Sitzung eine eigene und
    # die Kontoauswahl bliebe bewusst unangetastet.
    window.current_user.own_accounts = []
    ws.selected_login_account = "OTHER\\tester"
    chooser = Mock(return_value=("", False))
    monkeypatch.setattr(module.QInputDialog, "getItem", chooser)
    window._refresh_login_views = Mock()
    module.MainWindow.on_connect_requested(window, ws)
    chooser.assert_not_called()
    assert launcher.call_args.args[0].username_hint == "AzureAD\\tester"


def test_a_claimed_account_stops_the_portal_from_overriding_the_choice(monkeypatch):
    """Ist die Sitzung als eigene erkannt, gilt die Kontoauswahl unveraendert."""
    import portal_app.rdp as rdp
    import portal_app.ui.main_window as module

    ws = machine()
    ws.trust_unverified_server = True
    ws.selected_login_account = "OTHER\\tester"
    window = SimpleNamespace(current_user=MockUser.create_user(), _record_event=Mock(),
                             _poll_rdp_sessions=Mock(), _refresh_login_views=Mock(),
                             _check_reservation_access=Mock(return_value=True),
                             _persist=Mock(), _refresh_workstation_views=Mock(), _saved_user=None)
    window.current_user.own_accounts = ["AzureAD\\tester"]
    launcher = Mock(return_value=(True, "started"))
    monkeypatch.setattr(rdp, "has_active_rdp_session", Mock(return_value=False))
    monkeypatch.setattr(rdp, "launch_rdp_session", launcher)
    monkeypatch.setattr(module.QMessageBox, "information", Mock())
    monkeypatch.setattr(module.QMessageBox, "warning", Mock())

    module.MainWindow.on_connect_requested(window, ws)

    assert launcher.call_args.args[0].username_hint == "OTHER\\tester"


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
                             _check_reservation_access=Mock(return_value=True),
                             _persist=Mock(), _refresh_workstation_views=Mock(), _saved_user=None)
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


def test_a_generated_portal_id_no_longer_blocks_the_logoff(native):
    """Der Livestatus akzeptierte den Hostnamen, die Abmeldung nicht -- jetzt beide."""
    native.snapshot.workstation_id = native.ended.workstation_id = "NB05"
    native.snapshot.hostname = native.ended.hostname = "NB05"

    logoff_own_session(
        "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "WS-003",
        hostnames={"nb05"},
    )

    native.agent_logoff.assert_called_once()


def test_the_agent_is_addressed_by_the_id_it_calls_itself(native):
    """Der Agent prueft die mitgeschickte ID gegen seine eigene und lehnt sonst ab."""
    native.snapshot.workstation_id = native.ended.workstation_id = "NB05"
    native.snapshot.hostname = native.ended.hostname = "NB05"

    logoff_own_session(
        "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "WS-003",
        hostnames={"nb05"},
    )

    assert native.agent_logoff.call_args.args[5] == "NB05"


def test_a_hostname_cannot_override_an_explicit_assignment(native):
    """hostnames=None heisst: die Zuordnung wurde von Hand gesetzt."""
    native.snapshot.workstation_id = native.ended.workstation_id = "NB05"
    native.snapshot.hostname = native.ended.hostname = "NB05"

    with pytest.raises(ValueError, match="zugeordnete Agent-ID"):
        logoff_own_session(
            "REMOTE", 3, "AzureAD\\tester", "2026-09-10T08:00:00+00:00", "WS-003",
        )

    native.agent_logoff.assert_not_called()
