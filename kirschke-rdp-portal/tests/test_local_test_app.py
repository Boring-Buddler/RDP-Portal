import sys
import json
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtWidgets import QApplication

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent, create_mock_session_logs
from portal_app.models.user import MockUser
from portal_app.models.workstation import (
    Workstation,
    create_initial_workstations,
    create_test_workstation,
)
from portal_app.rdp.generator import RDPFileGenerator
from portal_app.rdp.launcher import RDPSessionLauncher
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.local_store import LocalStore, StoreConflictError
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.directory_users import discover_windows_domain_accounts
from portal_app.services.active_directory_sync import check_active_directory_readiness, sync_rdp_group_members
from portal_app.services.windows_admin_auth import (
    check_windows_admin_authorization,
    test_password_fallback_allowed as is_test_password_fallback_allowed,
)
from portal_app.services.machine_discovery import MachineDiscovery, _ipconfig_network_details, discover_remote_machine
from portal_app.services.rdp_diagnostics import clear_saved_rdp_credentials, run_rdp_diagnostics
from portal_app.ui.main_window import MainWindow
from portal_app.ui.widgets.ping_tool import PingToolWidget
from portal_app.ui.widgets.management_pages import AdministrationWidget, SettingsWidget
from portal_app.ui.widgets.reservation_calendar import ReservationCalendarWidget, ReservationDialog
from portal_app.ui.widgets.session_log import event_to_export_row
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.workstation_dialog import WorkstationDialog
from portal_app.ui.widgets.machine_registration_wizard import MachineRegistrationWizard
from portal_app.ui.widgets.rdp_access_dialog import RDPAccessDialog
from shared.agent_snapshot import AgentSnapshot, load_agent_snapshots, write_agent_snapshot
from shared.enums import AgentStatus, ConnectionTargetMode, EventResult, EventType, SessionState
from workstation_agent.service import AgentConfig, WorkstationAgent
from workstation_agent.wts.monitor import WTSSessionInfo, WTS_CONNECTSTATE_CLASS


def test_local_store_roundtrip(tmp_path):
    workstation = create_test_workstation()
    user = MockUser.create_user()
    reservation = Reservation(
        workstation_id=workstation.workstation_id,
        title="Testlauf",
        start=datetime.now(),
        end=datetime.now() + timedelta(hours=2),
        reserved_by=user.upn,
    )
    store = LocalStore(tmp_path / "state.json")

    store.save([workstation], user, [reservation], theme_mode="dark")
    workstations, loaded_user, reservations = store.load([], MockUser.create_user())

    assert workstations[0].ip_address == workstation.ip_address
    assert loaded_user.get_rdp_username() == "KIRSCHKE\\user"
    assert reservations[0].title == "Testlauf"
    assert store.theme_mode == "dark"


def test_local_preferences_are_not_written_to_shared_portal_state(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()

    store.save([create_test_workstation()], user, [], theme_mode="dark")

    shared_data = json.loads(store.path.read_text(encoding="utf-8"))
    preferences = json.loads(store.preferences_path.read_text(encoding="utf-8"))
    assert shared_data["version"] == 4
    assert "user" not in shared_data
    assert "theme_mode" not in shared_data
    assert preferences["theme_mode"] == "dark"
    assert preferences["user"]["upn"] == user.upn


def test_shared_state_merges_independent_machine_changes(tmp_path):
    path = tmp_path / "portal-state.json"
    user = MockUser.create_user()
    initial = create_test_workstation()
    first = LocalStore(path)
    first.save([initial], user, [])
    second = LocalStore(path)
    first_workstations, _, _ = first.load([], user)
    second_workstations, _, _ = second.load([], user)
    first_added = Workstation(workstation_id="WS-FIRST", display_name="Erste", hostname="FIRST")
    second_added = Workstation(workstation_id="WS-SECOND", display_name="Zweite", hostname="SECOND")

    first.save(first_workstations + [first_added], user, [])
    second.save(second_workstations + [second_added], user, [])

    merged, _, _ = LocalStore(path).load([], user)
    assert {workstation.workstation_id for workstation in merged} == {
        initial.workstation_id,
        "WS-FIRST",
        "WS-SECOND",
    }


def test_shared_state_rejects_simultaneous_change_to_same_machine(tmp_path):
    path = tmp_path / "portal-state.json"
    user = MockUser.create_user()
    initial = create_test_workstation()
    first = LocalStore(path)
    first.save([initial], user, [])
    second = LocalStore(path)
    first_workstations, _, _ = first.load([], user)
    second_workstations, _, _ = second.load([], user)
    first_workstations[0].display_name = "Portal Eins"
    second_workstations[0].display_name = "Portal Zwei"

    first.save(first_workstations, user, [])
    with pytest.raises(StoreConflictError):
        second.save(second_workstations, user, [])


def test_local_store_removes_legacy_demo_machine_username(tmp_path):
    workstation = Workstation(
        workstation_id="WS-LEGACY-USER",
        display_name="Alte Testmaschine",
        hostname="PC-LEGACY",
        username_hint="user1@prof-kirschke.de",
    )
    store = LocalStore(tmp_path / "state.json")
    user = MockUser.create_user()
    store.save([workstation], user, [])

    workstations, _, _ = store.load([], user)

    assert workstations[0].username_hint is None
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert saved["workstations"][0]["username_hint"] is None


def test_local_store_writes_and_moves_shared_status_and_event_log(tmp_path):
    source = tmp_path / "source" / "portal-state.json"
    store = LocalStore(source)
    user = MockUser.create_user()
    workstation = create_test_workstation()
    store.save([workstation], user, [])
    store.initialize_event_log()
    store.append_event(
        SessionEvent(
            event_id="EVT-1",
            timestamp_utc=datetime.now(),
            event_type=EventType.LAUNCH_REQUESTED,
            workstation_id=workstation.workstation_id,
            result=EventResult.SUCCESS,
        )
    )

    target = tmp_path / "sharepoint" / "RDP-Portal"
    store.relocate(target)

    assert store.path == target / "portal-state.json"
    assert store.events_path == target / "portal-events.jsonl"
    assert store.path.exists()
    assert len(store.load_events()) == 1
    assert not source.exists()
    marker = json.loads((source.parent / "storage-location.json").read_text(encoding="utf-8"))
    assert marker["storage_directory"] == str(target)


def test_local_store_detects_external_shared_file_change(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()
    store.save([create_test_workstation()], user, [])

    assert not store.has_external_changes()
    store.path.write_text(store.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert store.has_external_changes()


def test_rdp_access_members_and_directory_cache_are_shared_and_moved(tmp_path):
    source = tmp_path / "source" / "portal-state.json"
    store = LocalStore(source)
    user = MockUser.create_user()
    workstation = create_test_workstation()
    workstation.rdp_access_users = ["KIRSCHKE\\becker"]
    store.save([workstation], user, [])
    assert store.save_directory_accounts(["KIRSCHKE\\becker", "user@firma.de"]) == [
        "KIRSCHKE\\becker",
        "user@firma.de",
    ]

    loaded, _, _ = store.load([], user)
    assert loaded[0].rdp_access_users == ["KIRSCHKE\\becker"]
    target = tmp_path / "sharepoint" / "RDP-Portal"
    store.relocate(target)
    assert store.directory_users_path == target / "portal-directory-users.json"
    assert store.load_directory_accounts() == ["KIRSCHKE\\becker", "user@firma.de"]


def test_remote_discovery_uses_reverse_dns(monkeypatch):
    monkeypatch.setattr(
        "portal_app.services.machine_discovery.socket.gethostbyaddr",
        lambda address: ("pc-cad-01.kirschke.local", [], [address]),
    )

    result = discover_remote_machine("192.168.2.68")

    assert result.hostname == "pc-cad-01"
    assert result.fqdn == "pc-cad-01.kirschke.local"
    assert result.ip_address == "192.168.2.68"


def test_windows_domain_lookup_returns_selectable_accounts(monkeypatch):
    class Result:
        returncode = 0
        stdout = """
User accounts for \\KIRSCHKE
-------------------------------------------------------------------------------
becker       mueller.test     service-rdp
The command completed successfully.
"""

    monkeypatch.setenv("USERDOMAIN", "KIRSCHKE")
    monkeypatch.setattr("portal_app.services.directory_users.subprocess.run", lambda *args, **kwargs: Result())
    result = discover_windows_domain_accounts()

    assert result.accounts == ["KIRSCHKE\\becker", "KIRSCHKE\\mueller.test", "KIRSCHKE\\service-rdp"]


def test_ad_group_sync_uses_current_windows_context_without_passwords(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = '{"added":["becker"],"removed":["altuser"]}'
        stderr = ""

    def fake_run(*args, **kwargs):
        captured["args"] = args[0]
        captured["kwargs"] = kwargs
        return Result()

    monkeypatch.setattr("portal_app.services.active_directory_sync.subprocess.run", fake_run)
    result = sync_rdp_group_members("RDP-WS-001", ["KIRSCHKE\\becker"])

    assert result.success
    assert result.added == ["becker"]
    assert result.removed == ["altuser"]
    assert captured["args"][:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy"]
    assert "Import-Module ActiveDirectory" in captured["args"][-1]
    assert "password" not in captured["args"][-1].casefold()


def test_ipconfig_fallback_prefers_adapter_with_default_gateway(monkeypatch):
    class Result:
        returncode = 0
        stdout = """
Ethernet adapter VPN:
   IPv4 Address. . . . . . . . . . . : 100.82.35.95
   Subnet Mask . . . . . . . . . . . : 255.255.255.255

Ethernet adapter LAN:
   IPv4 Address. . . . . . . . . . . : 192.168.2.77
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.2.1
   DNS Servers . . . . . . . . . . . : 192.168.2.1
"""

    monkeypatch.setattr("portal_app.services.machine_discovery.subprocess.run", lambda *args, **kwargs: Result())

    assert _ipconfig_network_details() == {
        "ip_address": "192.168.2.77",
        "subnet_mask": "255.255.255.0",
        "default_gateway": "192.168.2.1",
        "dns_server": "192.168.2.1",
    }


def test_registration_wizard_passes_detected_values_to_profile(qtbot):
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    assert wizard.objectName() == "machineRegistrationWizard"
    assert wizard.minimumWidth() >= 760
    assert wizard.minimumHeight() >= 600
    assert all(
        wizard.page(page_id).objectName() == "machineWizardPage"
        for page_id in (MachineRegistrationWizard.SOURCE_PAGE, MachineRegistrationWizard.PREVIEW_PAGE)
    )
    wizard.discovery = MachineDiscovery(
        hostname="PC-TEST",
        fqdn="pc-test.kirschke.local",
        ip_address="192.168.2.70",
        subnet_mask="255.255.255.0",
        default_gateway="192.168.2.1",
        dns_server="192.168.2.10",
        message="Erkannt",
    )
    preview = wizard.page(MachineRegistrationWizard.PREVIEW_PAGE)
    preview.initializePage()
    assert all(field.minimumHeight() >= 36 for field in preview.inputs.values())

    dialog = WorkstationDialog(suggested_id="WS-003", prefill=wizard.prefill)
    qtbot.addWidget(dialog)

    assert dialog.display_name.text() == "PC-TEST"
    assert dialog.hostname.text() == "PC-TEST"
    assert dialog.fqdn.text() == "pc-test.kirschke.local"


def test_dialog_inputs_keep_a_readable_height(qtbot):
    app = QApplication.instance()
    assert app is not None
    previous_style = app.styleSheet()
    app.setStyleSheet(MainWindow._application_style(False))
    try:
        profile = WorkstationDialog()
        reservation = ReservationDialog([create_test_workstation()], MockUser.create_user())
        qtbot.addWidget(profile)
        qtbot.addWidget(reservation)
        profile.show()
        reservation.show()
        qtbot.wait(20)
        assert profile.display_name.height() >= 36
        assert profile.hostname.height() >= 36
        assert reservation.title.height() >= 36
        assert reservation.start.height() >= 36
        assert reservation.end.height() >= 36
    finally:
        app.setStyleSheet(previous_style)


def test_initial_user_uses_whoami_for_default(monkeypatch):
    class Result:
        returncode = 0
        stdout = "KIRSCHKE\\alex\n"

    monkeypatch.setattr("portal_app.services.local_identity.subprocess.run", lambda *args, **kwargs: Result())

    user = detect_initial_user()

    assert user.display_name == "alex"
    assert user.upn == "KIRSCHKE\\alex"
    assert user.get_rdp_username() == "KIRSCHKE\\alex"


def test_initial_workstations_are_munich_and_ettlingen():
    workstations = create_initial_workstations()

    assert len(workstations) == 2
    assert {workstation.site for workstation in workstations} == {"München", "Ettlingen"}
    assert all(workstation.enabled for workstation in workstations)


def test_admin_actions_include_disconnect_and_delete(qtbot):
    workstations = create_initial_workstations()
    admin = AdministrationWidget(workstations)
    qtbot.addWidget(admin)
    admin.table.selectRow(0)

    assert admin.force_disconnect.text() == "Trennen"
    assert admin.force_disconnect.isEnabled()
    assert admin.delete_workstation.isEnabled()
    assert admin.rdp_access.isEnabled()
    with qtbot.waitSignal(admin.delete_requested) as signal:
        admin._delete_selected()
    assert signal.args == [workstations[0]]
    admin.set_storage_status("Gemeinsamer Stand gespeichert · 12:34:56")
    assert "12:34:56" in admin.storage_status.text()


def test_windows_admin_authorization_matches_domain_group(monkeypatch):
    class Result:
        returncode = 0
        stdout = '"KIRSCHKE\\RDP-Portal-Admins","S-1-5-21","Mandatory group, Enabled by default"\n'

    monkeypatch.setattr("portal_app.services.windows_admin_auth.subprocess.run", lambda *args, **kwargs: Result())
    result = check_windows_admin_authorization()

    assert result.authorized
    assert result.group_name == "RDP-Portal-Admins"


def test_test_admin_password_can_be_disabled_for_production(monkeypatch):
    monkeypatch.delenv("RDP_PORTAL_ALLOW_TEST_ADMIN_PASSWORD", raising=False)
    assert is_test_password_fallback_allowed()
    monkeypatch.setenv("RDP_PORTAL_ALLOW_TEST_ADMIN_PASSWORD", "false")
    assert not is_test_password_fallback_allowed()


def test_ad_readiness_reports_module_and_windows_admin_group(monkeypatch):
    class Authorization:
        authorized = True
        group_name = "RDP-Portal-Admins"

    class Result:
        returncode = 0
        stdout = "installed\n"

    monkeypatch.setattr(
        "portal_app.services.active_directory_sync.check_windows_admin_authorization",
        lambda: Authorization(),
    )
    monkeypatch.setattr("portal_app.services.active_directory_sync.subprocess.run", lambda *args, **kwargs: Result())
    readiness = check_active_directory_readiness()

    assert readiness.module_available
    assert readiness.admin_authorized
    assert "verfügbar" in readiness.message


def test_rdp_access_dialog_selects_and_manually_adds_accounts(qtbot):
    app = QApplication.instance()
    assert app is not None
    previous_style = app.styleSheet()
    app.setStyleSheet(MainWindow._application_style(False))
    try:
        dialog = RDPAccessDialog(
            create_test_workstation(),
            ["KIRSCHKE\\becker"],
            "1 Benutzer aus der Windows-Domäne gefunden.",
        )
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.wait(20)
        assert dialog.search.height() >= 36
        dialog.directory_list.setCurrentRow(0)
        dialog._add_selected()
        dialog.manual_account.setText("mueller@firma.de")
        dialog._add_manual()
        assert dialog.selected_members == ["KIRSCHKE\\becker", "mueller@firma.de"]
        assert "mueller@firma.de" in dialog.known_accounts
        dialog._accept_for_active_directory()
        assert dialog.sync_to_active_directory
    finally:
        app.setStyleSheet(previous_style)


def test_calendar_keeps_toolbar_compact_and_edits_by_double_click(qtbot):
    workstation = create_test_workstation()
    reservation = Reservation(
        workstation_id=workstation.workstation_id,
        title="Reservierter Test",
        start=datetime.combine(datetime.today().date(), datetime.min.time()),
        end=datetime.combine(datetime.today().date() + timedelta(days=1), datetime.min.time()),
        reserved_by="user@example.com",
    )
    calendar = ReservationCalendarWidget([workstation], [reservation], MockUser.create_user())
    qtbot.addWidget(calendar)
    assert not hasattr(calendar, "edit_reservation_btn")
    assert not hasattr(calendar, "delete_reservation_btn")


def test_settings_content_is_scrollable_and_keeps_card_space(qtbot):
    settings = SettingsWidget(MockUser.create_user())
    qtbot.addWidget(settings)

    assert settings.scroll.widget().objectName() == "settingsContent"
    cards = settings.scroll.widget().findChildren(type(settings.identity.parent()))
    assert any(card.minimumHeight() >= 176 for card in cards)


def test_dark_theme_has_high_contrast_palette():
    style = MainWindow._application_style(True)

    assert "#101820" in style
    assert "#f4f8fb" in style
    assert "QWizard#machineRegistrationWizard > QWidget" in style
    assert "QLineEdit#dashboardSearch:focus, QLineEdit#pingInput:focus" in style
    assert "QWizard QPushButton:default { background: #5b91b1; color: #ffffff;" in style
    assert "QMessageBox QPushButton" in style
    assert "QDialogButtonBox QPushButton" in style
    assert "QComboBox QAbstractItemView" in style


def test_main_window_starts_with_two_machines_and_persists_theme(tmp_path, monkeypatch, qtbot):
    store = LocalStore(tmp_path / "state.json")
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow()
    qtbot.addWidget(window)

    assert [workstation.site for workstation in window.workstations] == ["München", "Ettlingen"]
    window._set_dark_mode(True)

    assert window.dark_mode
    assert window.settings_view.theme_toggle_button.text() == "Zum Hellmodus wechseln"
    assert not hasattr(window, "theme_button")
    logo = window.logo_label.pixmap().toImage()
    logo_pixels = [
        logo.pixelColor(x, y)
        for y in range(logo.height())
        for x in range(logo.width())
        if logo.pixelColor(x, y).alpha() > 200
    ]
    assert logo_pixels
    assert all(color.red() > 240 and color.green() > 240 and color.blue() > 240 for color in logo_pixels)
    assert json.loads(store.preferences_path.read_text(encoding="utf-8"))["theme_mode"] == "dark"


def test_machine_username_overrides_user_default(tmp_path):
    workstation = create_test_workstation()
    workstation.username_hint = "LAB\\maschine"
    profile = workstation.get_rdp_profile("KIRSCHKE\\standard")
    generator = RDPFileGenerator(str(tmp_path))

    path = generator.generate(profile)
    content = open(path, encoding="utf-8").read()

    assert "username:s:LAB\\maschine" in content
    assert "full address:s:" in content


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (ConnectionTargetMode.AUTO, "pc-01.example.local"),
        (ConnectionTargetMode.IP_ADDRESS, "192.168.20.41"),
        (ConnectionTargetMode.HOSTNAME, "PC-01"),
        (ConnectionTargetMode.FQDN, "pc-01.example.local"),
    ],
)
def test_rdp_connection_target_modes(tmp_path, mode, expected):
    workstation = Workstation(
        workstation_id="WS-TARGET",
        display_name="Zieltest",
        hostname="PC-01",
        fqdn="pc-01.example.local",
        ip_address="192.168.20.41",
        connection_target_mode=mode,
    )
    generator = RDPFileGenerator(str(tmp_path))

    path = generator.generate(workstation.get_rdp_profile())
    content = open(path, encoding="utf-8").read()

    assert f"full address:s:{expected}" in content


def test_ip_target_disables_web_account_in_rdp_file(tmp_path):
    workstation = Workstation(
        workstation_id="WS-IP",
        display_name="IP-Test",
        hostname="",
        ip_address="192.168.20.42",
        connection_target_mode=ConnectionTargetMode.IP_ADDRESS,
        entra_sso_enabled=True,
    )
    profile = workstation.get_rdp_profile("user@example.com")
    generator = RDPFileGenerator(str(tmp_path))

    path = generator.generate(profile)
    content = open(path, encoding="utf-8").read()

    assert profile.entra_sso_enabled
    assert not profile.effective_entra_sso_enabled()
    assert "full address:s:192.168.20.42" in content
    assert "enablerdsaadauth:i:0" in content
    assert "enablerdsaadauth:i:1" not in content


def test_legacy_ip_in_hostname_field_also_disables_web_account(tmp_path):
    workstation = Workstation(
        workstation_id="WS-LEGACY-IP",
        display_name="Bestehender IP-Eintrag",
        hostname="192.168.20.43",
        connection_target_mode=ConnectionTargetMode.AUTO,
        entra_sso_enabled=True,
    )
    profile = workstation.get_rdp_profile()
    generator = RDPFileGenerator(str(tmp_path))

    path = generator.generate(profile)
    content = open(path, encoding="utf-8").read()

    assert profile.uses_ip_target()
    assert "full address:s:192.168.20.43" in content
    assert "enablerdsaadauth:i:0" in content


def test_hostname_target_keeps_web_account_in_rdp_file(tmp_path):
    workstation = Workstation(
        workstation_id="WS-HOST",
        display_name="Hostname-Test",
        hostname="PC-01",
        ip_address="192.168.20.42",
        connection_target_mode=ConnectionTargetMode.HOSTNAME,
        entra_sso_enabled=True,
    )
    generator = RDPFileGenerator(str(tmp_path))

    path = generator.generate(workstation.get_rdp_profile())
    content = open(path, encoding="utf-8").read()

    assert "full address:s:PC-01" in content
    assert "enablerdsaadauth:i:1" in content


def test_server_identity_warning_is_only_suppressed_after_explicit_trust(tmp_path):
    workstation = Workstation(
        workstation_id="WS-TRUST",
        display_name="GeprÃ¼fte Maschine",
        hostname="PC-TRUST",
        trust_unverified_server=True,
    )
    generator = RDPFileGenerator(str(tmp_path))

    trusted_path = generator.generate(workstation.get_rdp_profile())
    trusted_content = open(trusted_path, encoding="utf-8").read()
    untrusted_path = generator.generate(
        Workstation(
            workstation_id="WS-NO-TRUST",
            display_name="UngeprÃ¼fte Maschine",
            hostname="PC-NO-TRUST",
        ).get_rdp_profile()
    )
    untrusted_content = open(untrusted_path, encoding="utf-8").read()

    assert "authentication level:i:0" in trusted_content
    assert "authentication level:i:0" not in untrusted_content


def test_workstation_dialog_accepts_ip_only_profile(qtbot):
    dialog = WorkstationDialog(suggested_id="WS-IP-ONLY")
    qtbot.addWidget(dialog)
    dialog.display_name.setText("Nur per IP")
    dialog.hostname.clear()
    dialog.ip_address.setText("192.168.20.50")
    dialog.connection_target.setCurrentIndex(
        dialog.connection_target.findData(ConnectionTargetMode.IP_ADDRESS.value)
    )

    dialog._accept()

    assert dialog.workstation is not None
    assert dialog.workstation.hostname == ""
    assert dialog.workstation.connection_target_mode == ConnectionTargetMode.IP_ADDRESS


def test_user_default_is_used_without_machine_username():
    workstation = create_test_workstation()
    workstation.username_hint = None

    profile = workstation.get_rdp_profile("KIRSCHKE\\standard")

    assert profile.username_hint == "KIRSCHKE\\standard"


def test_rdp_diagnostics_reports_reachable_port_without_credentials(monkeypatch, tmp_path):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("192.168.20.60", 3389))],
    )
    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics.socket.create_connection",
        lambda *args, **kwargs: Connection(),
    )
    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics._recent_rdp_client_events",
        lambda: "[RDP-Client]\nFehlercode: Beispiel",
    )
    monkeypatch.setattr(
        "portal_app.services.rdp_diagnostics._has_saved_rdp_credentials",
        lambda target: True,
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    profile = Workstation(
        workstation_id="WS-DIAG",
        display_name="Diagnose",
        hostname="PC-DIAG",
        username_hint="KIRSCHKE\\becker",
    ).get_rdp_profile()

    result = run_rdp_diagnostics(profile)

    assert result.port_open
    assert "TCP-Port 3389 (RDP): ERREICHBAR" in result.report
    assert "KIRSCHKE\\becker" in result.report
    assert "Passwort: wird nicht protokolliert" in result.report
    assert "Fehlercode: Beispiel" in result.report
    assert "Gespeicherte Windows-Anmeldedaten" in result.report
    assert result.saved_credentials_present
    assert result.log_path.exists()


def test_clear_saved_rdp_credentials_removes_only_selected_target(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr("portal_app.services.rdp_diagnostics.subprocess.run", run)

    success, message = clear_saved_rdp_credentials("192.168.2.68")

    assert success
    assert "TERMSRV/192.168.2.68" in message
    assert calls == [["cmdkey", "/delete:TERMSRV/192.168.2.68"]]


@pytest.mark.parametrize(
    "state",
    [
        SessionState.LOGON,
        SessionState.CONNECTED,
        SessionState.RECONNECTED,
        SessionState.DISCONNECTED,
    ],
)
def test_active_and_disconnected_sessions_block_connection(state):
    workstation = create_test_workstation()
    workstation.current_session_state = state

    assert workstation.has_active_session()
    assert not workstation.can_connect()


def test_logged_off_session_allows_connection():
    workstation = create_test_workstation()
    workstation.current_session_state = SessionState.LOGGED_OFF

    assert not workstation.has_active_session()
    assert workstation.can_connect()


def test_rdp_launcher_tracks_process_lifetime(tmp_path, monkeypatch):
    class FakeProcess:
        pid = 4711
        return_code = None

        def poll(self):
            return self.return_code

    process = FakeProcess()
    launcher = RDPSessionLauncher(RDPFileGenerator(str(tmp_path)))
    monkeypatch.setattr(launcher, "_find_mstsc", lambda: "mstsc.exe")
    monkeypatch.setattr("portal_app.rdp.launcher.subprocess.Popen", lambda *args, **kwargs: process)
    workstation = create_test_workstation()

    success, _ = launcher.launch(
        workstation.get_rdp_profile(),
        workstation.workstation_id,
        workstation.display_name,
    )

    assert success
    assert launcher.has_active_session(workstation.workstation_id)
    assert launcher.get_active_sessions()[0].pid == 4711

    process.return_code = 0
    assert launcher.get_active_sessions() == []
    finished = launcher.consume_finished_sessions()
    assert len(finished) == 1
    assert finished[0].return_code == 0


def test_rdp_launcher_force_disconnects_only_selected_machine(tmp_path, monkeypatch):
    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid
            self.return_code = None
            self.terminated = False

        def poll(self):
            return self.return_code

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.return_code = 1
            return self.return_code

        def kill(self):
            self.return_code = 1

    first_process = FakeProcess(4901)
    second_process = FakeProcess(4902)
    pending_processes = [first_process, second_process]
    launcher = RDPSessionLauncher(RDPFileGenerator(str(tmp_path)))
    monkeypatch.setattr(launcher, "_find_mstsc", lambda: "mstsc.exe")
    monkeypatch.setattr(
        "portal_app.rdp.launcher.subprocess.Popen",
        lambda *args, **kwargs: pending_processes.pop(0),
    )
    first = Workstation("WS-FIRST", "Erste Maschine", "pc-first")
    second = Workstation("WS-SECOND", "Zweite Maschine", "pc-second")
    launcher.launch(first.get_rdp_profile(), first.workstation_id, first.display_name)
    launcher.launch(second.get_rdp_profile(), second.workstation_id, second.display_name)

    disconnected, failures = launcher.disconnect_session(first.workstation_id)

    assert disconnected == 1
    assert failures == []
    assert first_process.terminated
    assert not second_process.terminated
    assert [session.workstation_id for session in launcher.get_active_sessions()] == ["WS-SECOND"]


def test_detail_warns_for_disconnected_session(qtbot):
    workstation = create_test_workstation()
    workstation.current_session_state = SessionState.DISCONNECTED
    workstation.current_session_user = "user@kirschke.local"
    detail = WorkstationDetailWidget(MockUser.create_user())
    qtbot.addWidget(detail)

    detail.set_workstation(workstation)

    assert not detail.connect_btn.isEnabled()
    assert not detail.session_warning.isHidden()
    assert "Getrennt" in detail.session_warning_text.text()


@pytest.mark.parametrize(
    ("age_seconds", "expected_status"),
    [
        (10, AgentStatus.ONLINE),
        (120, AgentStatus.STALE),
        (360, AgentStatus.OFFLINE),
    ],
)
def test_local_agent_snapshot_updates_matching_machine(
    tmp_path,
    monkeypatch,
    age_seconds,
    expected_status,
):
    monkeypatch.setenv("AGENT_STATUS_DIR", str(tmp_path))
    workstation = create_test_workstation()
    snapshot = AgentSnapshot(
        workstation_id=workstation.workstation_id,
        hostname=workstation.hostname,
        agent_version="1.1.0-test",
        observed_at_utc=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        current_session_state=SessionState.DISCONNECTED,
        current_session_user="KIRSCHKE\\testuser",
        current_windows_session_id=17,
    )
    write_agent_snapshot(snapshot)
    service = LocalAgentStatusService()

    changed = service.apply([workstation])

    assert changed == 1
    assert service.last_match_count == 1
    assert workstation.agent_status == expected_status
    assert workstation.current_session_state == SessionState.DISCONNECTED
    assert workstation.current_session_user == "KIRSCHKE\\testuser"
    assert workstation.current_windows_session_id == 17
    assert not workstation.can_connect()


def test_workstation_agent_publishes_real_session_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STATUS_DIR", str(tmp_path))

    class FakeMonitor:
        def get_rdp_sessions(self):
            return [
                WTSSessionInfo(
                    session_id=23,
                    username="testuser",
                    domain="KIRSCHKE",
                    display_name="RDP-Tcp#1",
                    connect_state=WTS_CONNECTSTATE_CLASS.WTSDisconnected,
                    session_state=SessionState.DISCONNECTED,
                    protocol_type=2,
                )
            ]

        def close(self):
            return None

    config = AgentConfig(
        workstation_id="WS-AGENT-TEST",
        hostname="agent-test",
        log_file="",
        publish_local_status=True,
    )
    agent = WorkstationAgent(config)
    agent._wts_monitor = FakeMonitor()

    assert agent.start()
    snapshots = load_agent_snapshots()

    assert agent.state.current_session_state == SessionState.DISCONNECTED
    assert agent.state.current_session_user == "KIRSCHKE\\testuser"
    assert snapshots[0].agent_status == AgentStatus.ONLINE
    assert snapshots[0].current_windows_session_id == 23
    assert snapshots[0].rdp_sessions[0]["session_state"] == "disconnected"

    agent.stop()
    assert load_agent_snapshots()[0].agent_status == AgentStatus.OFFLINE


def test_admin_password_is_case_sensitive():
    assert MainWindow._is_admin_password_valid("Kirschke")
    assert not MainWindow._is_admin_password_valid("kirschke")
    assert not MainWindow._is_admin_password_valid("")


def test_session_event_export_contains_audit_fields():
    event = create_mock_session_logs(1)[0].events[0]

    row = event_to_export_row(event)

    assert row["workstation_id"] == event.workstation_id
    assert row["event_type"] == event.event_type.value
    assert row["source"] == event.source.value


def test_free_ping_rejects_command_options(qtbot):
    tool = PingToolWidget()
    qtbot.addWidget(tool)
    tool.target.setText("-n 20 localhost")

    tool.start_ping()

    assert tool.process is None
    assert tool.result.text() == "Ungültiges Ziel"


@pytest.mark.skipif(sys.platform != "win32", reason="ipconfig is a Windows system program")
def test_settings_show_and_copy_ipconfig(qtbot):
    settings = SettingsWidget(MockUser.create_user())
    qtbot.addWidget(settings)
    settings.load_network_info()

    qtbot.waitUntil(lambda: settings.ipconfig_process is None, timeout=5000)

    output = settings.network_output.toPlainText()
    assert len(output) > 50
    assert "IP" in output
    assert settings.copy_network_btn.isEnabled()
    settings._copy_network_info()
    assert QApplication.clipboard().text() == output


@pytest.mark.skipif(sys.platform != "win32", reason="The desktop application targets Windows ping.exe")
def test_free_and_machine_ping_localhost(qtbot):
    tool = PingToolWidget()
    qtbot.addWidget(tool)
    tool.target.setText("127.0.0.1")
    tool.start_ping()
    qtbot.waitUntil(lambda: tool.process is None, timeout=5000)
    assert tool.result.text().startswith("Erreichbar")

    workstation = create_test_workstation()
    workstation.ip_address = "127.0.0.1"
    detail = WorkstationDetailWidget(MockUser.create_user())
    qtbot.addWidget(detail)
    detail.set_workstation(workstation)
    detail._on_ping()
    qtbot.waitUntil(lambda: detail.ping_process is None, timeout=5000)
    assert detail.ping_result.text() == "Erreichbar"
