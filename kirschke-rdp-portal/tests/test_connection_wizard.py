"""The connection assistant: site derivation, agent sweep and automatic fallback."""

from pathlib import Path

import pytest
import pywintypes
import win32cred
import win32pipe
import win32wnet
from PySide6.QtCore import Qt

from portal_app.models.workstation import Workstation
from portal_app.services import agent_discovery, share_connection
from portal_app.services.agent_discovery import AgentProbe
from portal_app.services.machine_discovery import MachineDiscovery
from portal_app.services.site_mapping import known_sites, site_for_address
from portal_app.ui.widgets.agent_connection_panel import AUTOMATIC, AgentConnectionPanel
from portal_app.ui.widgets.machine_registration_wizard import (
    NEW_MACHINE,
    AgentAssignment,
    MachineRegistrationWizard,
)
from shared.agent_snapshot import AgentSnapshot


@pytest.fixture(autouse=True)
def no_real_share_reads(monkeypatch):
    r"""Never let these tests touch a real SMB share.

    The fallback paths under test are UNC paths to machines that do not exist
    here. Reading one blocks for the SMB timeout, and the worker thread holding
    that read keeps QThreadPool from being torn down -- which hangs the run
    rather than failing it.
    """
    from portal_app.services.agent_status import DirectoryScan, LocalAgentStatusService

    monkeypatch.setattr(
        LocalAgentStatusService,
        "scan_directories",
        staticmethod(
            lambda directories: {
                key: DirectoryScan(directory, [], [], [])
                for key, directory in directories.items()
            }
        ),
    )


def snapshot(workstation_id="PILOT-01", hostname="NB12KI"):
    return AgentSnapshot(
        workstation_id=workstation_id,
        hostname=hostname,
        agent_version="1.5.1",
    )


# --- Standort aus der Adresse ------------------------------------------------


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.168.2.68", "Ettlingen"),
        ("192.168.2.1", "Ettlingen"),
        ("192.168.20.5", "München"),
        ("192.168.20.254", "München"),
        ("10.0.0.5", ""),
        ("NB12KI", ""),
        ("", ""),
        (None, ""),
        ("fe80::1", ""),
    ],
)
def test_site_follows_the_address_range(address, expected):
    assert site_for_address(address) == expected


def test_munich_range_is_not_swallowed_by_the_ettlingen_prefix():
    """A string prefix would file every 192.168.20.x machine in Ettlingen."""
    assert "192.168.20.5".startswith("192.168.2")
    assert site_for_address("192.168.20.5") != site_for_address("192.168.2.5")


def test_known_sites_are_offered_without_duplicates():
    assert known_sites() == ["Ettlingen", "München"]


def test_discovery_prefill_carries_the_site():
    discovery = MachineDiscovery(hostname="NB12KI", ip_address="192.168.20.7")
    assert discovery.as_prefill()["site"] == "München"


# --- Suchbereich -------------------------------------------------------------


def test_sweep_expands_ranges_and_drops_duplicates():
    targets = agent_discovery.sweep_addresses(["192.168.2.0/30", "192.168.2.1", "NB12KI"])
    assert targets == ["192.168.2.1", "192.168.2.2", "NB12KI"]


def test_sweep_refuses_a_range_nobody_could_believe_was_scanned():
    with pytest.raises(ValueError, match="Adressen"):
        agent_discovery.sweep_addresses(["10.0.0.0/16"])


def test_sweep_ignores_blank_and_malformed_entries():
    assert agent_discovery.sweep_addresses(["", "  ", "not/a/range"]) == []


# --- Einzelprüfung eines Ziels ----------------------------------------------


def test_probe_identifies_an_agent_that_answers(monkeypatch):
    monkeypatch.setattr(agent_discovery, "pipe_present", lambda *a, **k: True)
    monkeypatch.setattr(agent_discovery, "request_snapshot", lambda target: (snapshot(), 12))
    probe = agent_discovery.probe_agent("192.168.2.68")
    assert probe.agent_present and probe.identified
    assert probe.workstation_id == "PILOT-01"
    assert probe.hostname == "NB12KI"
    assert "NB12KI" in probe.label()


def test_probe_reports_a_running_agent_it_may_not_read(monkeypatch):
    """The pipe is there but the reader account is missing -- a different case
    from 'no agent', and the only one worth offering credentials for."""
    monkeypatch.setattr(agent_discovery, "pipe_present", lambda *a, **k: True)

    def denied(target):
        raise pywintypes.error(5, "CreateFile", "Zugriff verweigert")

    monkeypatch.setattr(agent_discovery, "request_snapshot", denied)
    probe = agent_discovery.probe_agent("192.168.2.68")
    assert probe.agent_present and not probe.identified
    assert "nicht lesbar" in probe.message


def test_probe_reports_no_agent_when_the_pipe_is_absent(monkeypatch):
    monkeypatch.setattr(agent_discovery, "pipe_present", lambda *a, **k: False)
    probe = agent_discovery.probe_agent("192.168.2.99")
    assert not probe.agent_present and not probe.identified


def test_probe_rejects_a_target_the_pipe_layer_would_refuse():
    assert not agent_discovery.probe_agent(r"\\evil\share").agent_present


def test_pipe_presence_counts_access_denied_as_an_agent(monkeypatch):
    def denied(path, timeout):
        raise pywintypes.error(5, "WaitNamedPipe", "Zugriff verweigert")

    monkeypatch.setattr(win32pipe, "WaitNamedPipe", denied)
    assert agent_discovery.pipe_present("192.168.2.68")


def test_pipe_presence_counts_file_not_found_as_no_agent(monkeypatch):
    def missing(path, timeout):
        raise pywintypes.error(2, "WaitNamedPipe", "nicht gefunden")

    monkeypatch.setattr(win32pipe, "WaitNamedPipe", missing)
    assert not agent_discovery.pipe_present("192.168.2.99")


def test_probe_prefill_prefers_the_name_the_agent_states(monkeypatch):
    monkeypatch.setattr(
        agent_discovery,
        "discover_remote_machine",
        lambda target: MachineDiscovery(hostname="falsch", ip_address="192.168.2.68"),
    )
    values = agent_discovery.probe_prefill(
        AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())
    )
    assert values["hostname"] == "NB12KI"
    assert values["display_name"] == "NB12KI"
    assert values["site"] == "Ettlingen"


# --- Gemeinsames Lesekonto und Wiederverbinden -------------------------------


def test_reader_credentials_live_in_windows_only(monkeypatch):
    written = []
    monkeypatch.setattr(win32cred, "CredWrite", lambda payload, flags: written.append(payload))
    assert share_connection.save_reader_credentials("PortalLeser", "test-secret") == "PortalLeser"
    assert written[0]["TargetName"] == share_connection.READER_CREDENTIAL_TARGET
    assert written[0]["Type"] == win32cred.CRED_TYPE_GENERIC
    assert written[0]["CredentialBlob"] == "test-secret"


def test_reader_credentials_reject_control_characters(monkeypatch):
    monkeypatch.setattr(win32cred, "CredWrite", lambda *a: pytest.fail("must not be written"))
    with pytest.raises(ValueError, match="Steuerzeichen"):
        share_connection.save_reader_credentials("Portal\r\nLeser", "secret")


def test_missing_reader_credentials_are_not_an_error(monkeypatch):
    def absent(*args):
        raise pywintypes.error(1168, "CredRead", "nicht gefunden")

    monkeypatch.setattr(win32cred, "CredRead", absent)
    assert share_connection.load_reader_credentials() is None
    assert share_connection.reader_account_name() == ""


def test_reader_credentials_decode_the_stored_blob(monkeypatch):
    monkeypatch.setattr(
        win32cred,
        "CredRead",
        lambda *a: {"UserName": "PortalLeser", "CredentialBlob": "geheim".encode("utf-16-le")},
    )
    assert share_connection.load_reader_credentials() == ("PortalLeser", "geheim")


def test_reconnect_builds_one_session_per_server(monkeypatch):
    """Two machines behind one server must not produce a second, pointless
    WNetAddConnection2 that Windows would only answer with 1219."""
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: ("PortalLeser", "s"))
    calls = []
    monkeypatch.setattr(
        win32wnet, "WNetAddConnection2", lambda *a: calls.append((a[0].lpRemoteName, a[2]))
    )
    results = share_connection.reconnect_status_shares(
        {
            "WS-001": r"\\NB12KI\RDP-Status",
            "WS-002": r"\\NB12KI\RDP-Status",
            "WS-003": r"\\NB07\RDP-Status",
        }
    )
    assert [name for name, _ in calls] == [r"\\NB12KI\RDP-Status", r"\\NB07\RDP-Status"]
    assert calls[0][1] == r"NB12KI\PortalLeser"
    assert all(success for success, _ in results.values())
    assert set(results) == {"WS-001", "WS-002", "WS-003"}


def test_reconnect_skips_local_paths(monkeypatch):
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    monkeypatch.setattr(win32wnet, "WNetAddConnection2", lambda *a: pytest.fail("kein UNC-Pfad"))
    assert share_connection.reconnect_status_shares({"WS-001": r"C:\lokal"}) == {}


def test_existing_connection_under_another_account_is_not_a_failure(monkeypatch):
    def conflict(*args):
        raise pywintypes.error(1219, "WNetAddConnection2", "Konflikt")

    monkeypatch.setattr(win32wnet, "WNetAddConnection2", conflict)
    success, message = share_connection.ensure_share_connection(r"\\NB12KI\RDP-Status")
    assert success and "bestehende" in message


def test_unreachable_share_reports_without_raising(monkeypatch):
    def unreachable(*args):
        raise pywintypes.error(53, "WNetAddConnection2", "nicht gefunden")

    monkeypatch.setattr(win32wnet, "WNetAddConnection2", unreachable)
    success, message = share_connection.ensure_share_connection(r"\\NB99\RDP-Status")
    assert not success and "53" in message


# --- Assistent ---------------------------------------------------------------


def test_wizard_routes_scan_and_manual_to_different_pages(qtbot):
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    source = wizard.page(MachineRegistrationWizard.SOURCE_PAGE)
    assert source.scan.isChecked()
    assert source.nextId() == MachineRegistrationWizard.SCAN_PAGE
    source.local.setChecked(True)
    assert source.nextId() == MachineRegistrationWizard.PREVIEW_PAGE


def test_wizard_requires_a_target_only_on_the_manual_route(qtbot):
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    source = wizard.page(MachineRegistrationWizard.SOURCE_PAGE)
    assert source.isComplete()
    source.remote.setChecked(True)
    assert not source.isComplete()
    source.target.setText("192.168.2.68")
    assert source.isComplete()


def test_scan_page_preselects_only_actionable_agents(qtbot):
    existing = Workstation(
        workstation_id="WS-001",
        display_name="Vorhanden",
        hostname="NB12KI",
        agent_workstation_id="PILOT-01",
    )
    wizard = MachineRegistrationWizard(workstations=[existing])
    qtbot.addWidget(wizard)
    page = wizard.page(MachineRegistrationWizard.SCAN_PAGE)
    page._on_found(AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot()))
    page._on_found(
        AgentProbe("192.168.2.70", agent_present=True, snapshot=snapshot("PILOT-02", "NB07"))
    )
    page._on_found(AgentProbe("192.168.2.90", agent_present=True, message="nicht lesbar"))
    states = [page.results.item(i).checkState().value for i in range(page.results.count())]
    # Already claimed, free, and unidentified.
    assert states == [0, 2, 0]
    assert "bereits zugeordnet zu Vorhanden" in page.results.item(0).text()
    assert [p.target for p in page._checked_probes()] == ["192.168.2.70"]


def test_assign_page_builds_assignments_and_skips_what_was_skipped(qtbot):
    existing = Workstation(workstation_id="WS-001", display_name="Vorhanden", hostname="NB07")
    wizard = MachineRegistrationWizard(workstations=[existing])
    qtbot.addWidget(wizard)
    wizard.probes = [
        AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot()),
        AgentProbe("192.168.20.9", agent_present=True, snapshot=snapshot("PILOT-02", "MUC01")),
    ]
    page = wizard.page(MachineRegistrationWizard.ASSIGN_PAGE)
    page.initializePage()
    assert page.table.rowCount() == 2
    # The site column follows the address of each agent.
    assert page.table.cellWidget(0, 3).currentText() == "Ettlingen"
    assert page.table.cellWidget(1, 3).currentText() == "München"
    assert page.table.cellWidget(0, 1).currentData() == NEW_MACHINE
    page.table.cellWidget(1, 1).setCurrentIndex(
        page.table.cellWidget(1, 1).findData("WS-001")
    )
    page.validatePage()
    assert len(wizard.assignments) == 2
    assert wizard.assignments[0].creates_machine
    assert wizard.assignments[1].workstation_id == "WS-001"


def test_assign_page_honours_skip(qtbot):
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    wizard.probes = [AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())]
    page = wizard.page(MachineRegistrationWizard.ASSIGN_PAGE)
    page.initializePage()
    combo = page.table.cellWidget(0, 1)
    combo.setCurrentIndex(combo.count() - 1)
    page.validatePage()
    assert wizard.assignments == []


def test_assignment_prefill_keeps_edited_name_and_site(monkeypatch):
    monkeypatch.setattr(
        agent_discovery,
        "discover_remote_machine",
        lambda target: MachineDiscovery(hostname="NB12KI", ip_address="192.168.2.68"),
    )
    assignment = AgentAssignment(
        probe=AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot()),
        display_name="CAD-Rechner",
        site="Ettlingen (Labor)",
    )
    values = assignment.prefill()
    assert values["display_name"] == "CAD-Rechner"
    assert values["site"] == "Ettlingen (Labor)"


# --- Zentrale Einstellungsseite ---------------------------------------------


def test_panel_lists_machines_with_their_mapping_and_fallback(qtbot):
    panel = AgentConnectionPanel()
    qtbot.addWidget(panel)
    panel.set_known_agents(["PILOT-01", "PILOT-02"])
    machine = Workstation(
        workstation_id="WS-001",
        display_name="CAD",
        hostname="NB12KI",
        agent_workstation_id="PILOT-01",
        agent_status_source="live",
        agent_fallback_directory=r"\\NB12KI\RDP-Status",
        agent_fallback_is_explicit=True,
    )
    panel.set_workstations([machine])
    assert panel.table.rowCount() == 1
    assert panel.table.cellWidget(0, 1).currentData() == "PILOT-01"
    assert panel.table.item(0, 2).text() == "Live-Kanal"
    assert panel.table.item(0, 3).text() == r"\\NB12KI\RDP-Status"
    assert "1 von 1" in panel.summary.text()


def test_panel_reports_a_changed_assignment_once(qtbot):
    panel = AgentConnectionPanel()
    qtbot.addWidget(panel)
    panel.set_known_agents(["PILOT-01"])
    changes = []
    panel.agent_assignment_changed.connect(lambda ws, agent: changes.append((ws, agent)))
    panel.set_workstations(
        [Workstation(workstation_id="WS-001", display_name="CAD", hostname="NB12KI")]
    )
    # Filling the table must not look like a user decision.
    assert changes == []
    combo = panel.table.cellWidget(0, 1)
    combo.setCurrentIndex(combo.findData("PILOT-01"))
    assert changes == [("WS-001", "PILOT-01")]
    combo.setCurrentIndex(combo.findData(AUTOMATIC))
    assert changes[-1] == ("WS-001", "")


def test_panel_never_emits_a_password_it_was_not_given(qtbot):
    panel = AgentConnectionPanel()
    qtbot.addWidget(panel)
    emitted = []
    panel.credentials_save_requested.connect(lambda u, p: emitted.append((u, p)))
    panel.reader_user.setText("PortalLeser")
    panel.save_credentials_button.click()
    assert emitted == []
    panel.reader_password.setText("test-secret")
    panel.save_credentials_button.click()
    assert emitted == [("PortalLeser", "test-secret")]
    # The field is cleared so the password does not sit in a widget afterwards.
    assert panel.reader_password.text() == ""


# --- Zusammenspiel im Hauptfenster -------------------------------------------


@pytest.fixture
def window_with_store(tmp_path, monkeypatch, qtbot):
    """A portal whose store is isolated and whose network calls are stubbed."""
    from portal_app.models.user import MockUser
    from portal_app.services.local_store import LocalStore
    from portal_app.ui.main_window import MainWindow

    #: Every message box the window would have shown, as (title, text).
    reported: list[tuple[str, str]] = []

    def build(workstations=()):
        store = LocalStore(tmp_path / "inventory" / "portal-state.json")
        store.save(list(workstations), MockUser.create_user(), [])
        monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
        # The assistant reports its result in a modal box. Unattended, that box
        # is never dismissed and the test simply stops there, so capture both
        # kinds rather than letting one block the run.
        for kind in ("information", "warning"):
            monkeypatch.setattr(
                f"portal_app.ui.main_window.QMessageBox.{kind}",
                lambda *args, **kwargs: reported.append((args[1], args[2])),
            )
        monkeypatch.setattr(
            agent_discovery,
            "discover_remote_machine",
            lambda target: MachineDiscovery(
                hostname="NB12KI", ip_address="192.168.2.68", subnet_mask="255.255.255.0"
            ),
        )
        window = MainWindow(automatic_live_status=False)
        qtbot.addWidget(window)
        return window, store

    build.reported = reported
    return build


def test_assignment_creates_a_machine_with_agent_site_and_fallback(window_with_store, monkeypatch):
    window, store = window_with_store()
    connected = []
    monkeypatch.setattr(
        "portal_app.services.share_connection.ensure_share_connection",
        lambda path, *creds: (connected.append(path) or (True, "verbunden")),
    )
    probe = AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())
    window._apply_agent_assignments([AgentAssignment(probe=probe, site="Ettlingen")])

    assert len(window.workstations) == 1
    machine = window.workstations[0]
    assert machine.hostname == "NB12KI"
    assert machine.site == "Ettlingen"
    # The agent is recorded, so both channels can attribute its reports.
    assert machine.agent_workstation_id == "PILOT-01"
    # And the fallback is derived rather than typed in per machine.
    assert connected == [r"\\NB12KI\RDP-Status"]
    assert machine.agent_fallback_is_explicit
    # pathlib keeps the trailing separator on a UNC root; compare as paths.
    assert Path(machine.agent_fallback_directory) == Path(r"\\NB12KI\RDP-Status")
    # Persisted, not just held in memory.
    assert store.get_workstation_agent_status_directory(machine.workstation_id) == (
        Path(r"\\NB12KI\RDP-Status"),
        True,
    )


def test_assignment_links_an_existing_machine_without_creating_one(window_with_store, monkeypatch):
    existing = Workstation(workstation_id="WS-001", display_name="CAD", hostname="NB12KI")
    window, _ = window_with_store([existing])
    monkeypatch.setattr(
        "portal_app.services.share_connection.ensure_share_connection",
        lambda *a: (True, "verbunden"),
    )
    probe = AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())
    window._apply_agent_assignments(
        [AgentAssignment(probe=probe, workstation_id="WS-001", site="Ettlingen")]
    )
    assert len(window.workstations) == 1
    assert window.workstations[0].agent_workstation_id == "PILOT-01"
    assert window.workstations[0].site == "Ettlingen"


def test_assignment_refuses_an_agent_another_machine_already_claims(window_with_store, monkeypatch):
    claimed = Workstation(
        workstation_id="WS-001",
        display_name="Vorhanden",
        hostname="NB12KI",
        agent_workstation_id="PILOT-01",
    )
    window, _ = window_with_store([claimed])
    monkeypatch.setattr(
        "portal_app.services.share_connection.ensure_share_connection",
        lambda *a: pytest.fail("darf gar nicht erst verbinden"),
    )
    probe = AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())
    window._apply_agent_assignments([AgentAssignment(probe=probe)])
    assert len(window.workstations) == 1
    assert "bereits" in window_with_store.reported[-1][1]


def test_failed_share_connection_does_not_pin_an_unusable_fallback(window_with_store, monkeypatch):
    window, store = window_with_store()
    monkeypatch.setattr(
        "portal_app.services.share_connection.ensure_share_connection",
        lambda *a: (False, r"\\NB12KI\RDP-Status: Windows-Fehler 53."),
    )
    probe = AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot())
    window._apply_agent_assignments([AgentAssignment(probe=probe)])
    machine = window.workstations[0]
    # The machine and its agent assignment survive; only the fallback stays open,
    # because a path that cannot be read must not be recorded as the one to read.
    assert machine.agent_workstation_id == "PILOT-01"
    assert not machine.agent_fallback_is_explicit
    assert store.workstation_agent_status_directories == {}


def test_startup_reconnects_every_configured_share(tmp_path, monkeypatch, qtbot):
    from portal_app.models.user import MockUser
    from portal_app.services.local_store import LocalStore
    from portal_app.ui.main_window import MainWindow

    store = LocalStore(tmp_path / "inventory" / "portal-state.json")
    store.save([Workstation("WS-001", "CAD", "NB12KI")], MockUser.create_user(), [])
    store.set_workstation_agent_status_directory("WS-001", r"\\NB12KI\RDP-Status")
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    configured = window._configured_fallback_paths()
    assert {key: Path(value) for key, value in configured.items()} == {
        "WS-001": Path(r"\\NB12KI\RDP-Status")
    }

    reconnected = []
    monkeypatch.setattr(
        "portal_app.services.share_connection.reconnect_status_shares",
        lambda paths: (reconnected.append(paths) or dict.fromkeys(paths, (True, "verbunden"))),
    )
    window._reconnect_status_shares()
    qtbot.waitUntil(lambda: bool(reconnected))
    assert {key: Path(value) for key, value in reconnected[0].items()} == {
        "WS-001": Path(r"\\NB12KI\RDP-Status")
    }


def test_reconnect_failures_are_named_not_only_counted(window_with_store):
    window, _ = window_with_store()
    window._on_shares_reconnected(
        {
            "WS-001": (True, "verbunden"),
            "WS-002": (False, r"\\NB07\RDP-Status: Windows-Fehler 53."),
        }
    )
    status = window.settings_view.agent_connection.credentials_status.text()
    assert "1 von 2" in status
    assert "NB07" in status


def test_settings_table_assignment_reaches_the_inventory(window_with_store, monkeypatch):
    window, store = window_with_store([Workstation("WS-001", "CAD", "NB12KI")])
    window._discovered_agent_ids = ["PILOT-01"]
    window._refresh_agent_panel()
    combo = window.settings_view.agent_connection.table.cellWidget(0, 1)
    combo.setCurrentIndex(combo.findData("PILOT-01"))
    assert window.workstations[0].agent_workstation_id == "PILOT-01"
    assert _stored_agent_id(store) == "PILOT-01"


def _stored_agent_id(store):
    """Read the agent assignment back from disk, not from the live object."""
    from portal_app.models.user import MockUser
    from portal_app.services.local_store import LocalStore

    workstations, _, _ = LocalStore(store.path).load([], MockUser.create_user())
    return workstations[0].agent_workstation_id


# --- Tabellen, die mehrfach gefüllt werden -----------------------------------


def _orphan_cell_widgets(table):
    """Widgets still drawn in the viewport that no current cell owns.

    This is the defect in its own terms: the table draws something that is not
    part of its contents any more. Counting widgets would instead encode Qt
    internals -- an editable combo box carries its own line edit, for one.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    owned = [
        table.cellWidget(row, column)
        for row in range(table.rowCount())
        for column in range(table.columnCount())
        if table.cellWidget(row, column) is not None
    ]
    drawn = table.viewport().findChildren(QWidget, options=Qt.FindDirectChildrenOnly)
    return [widget for widget in drawn if not any(widget is own for own in owned)]


def test_assign_page_does_not_keep_widgets_of_an_earlier_visit(qtbot):
    """Going back a step and forward again used to leave the previous row's
    combo box and name field drawn across the new first row."""
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    page = wizard.page(MachineRegistrationWizard.ASSIGN_PAGE)

    wizard.probes = [
        AgentProbe("192.168.2.68", agent_present=True, snapshot=snapshot()),
        AgentProbe("192.168.2.70", agent_present=True, snapshot=snapshot("PILOT-07", "NB07")),
    ]
    page.initializePage()
    assert _orphan_cell_widgets(page.table) == []

    wizard.probes = [AgentProbe("192.168.20.9", agent_present=True, snapshot=snapshot("PILOT-02", "MUC01"))]
    page.initializePage()
    assert page.table.rowCount() == 1
    assert _orphan_cell_widgets(page.table) == []
    assert page.table.item(0, 0).data(Qt.UserRole).target == "192.168.20.9"


def test_settings_table_does_not_accumulate_widgets_on_refresh(qtbot):
    panel = AgentConnectionPanel()
    qtbot.addWidget(panel)
    machines = [
        Workstation(workstation_id="WS-001", display_name="CAD", hostname="NB12KI"),
        Workstation(workstation_id="WS-002", display_name="MUC", hostname="MUC01"),
    ]
    # The settings table is refilled on every status refresh.
    for _ in range(3):
        panel.set_workstations(machines)
    assert _orphan_cell_widgets(panel.table) == []

    panel.set_workstations(machines[:1])
    assert panel.table.rowCount() == 1
    assert _orphan_cell_widgets(panel.table) == []


# --- Mitgeliefertes gegen eingetragenes Lesekonto ----------------------------


#: Stand-in for whatever a real release would have built in.
RELEASE_SECRET = "release" + "-secret"


def _bundle(monkeypatch, account="PortalLeser", secret=RELEASE_SECRET):
    """Pretend this build shipped a reader account."""
    from portal_app.services import reader_account

    monkeypatch.setattr(reader_account, "BUNDLED_READER_ACCOUNT", account)
    monkeypatch.setattr(reader_account, "BUNDLED_READER_PASSWORD", secret)


def test_repository_ships_no_reader_password():
    """The password is a release step. A value here would be a secret in git."""
    from portal_app.services import reader_account

    assert reader_account.BUNDLED_READER_PASSWORD == ""
    assert reader_account.bundled_credentials() is None
    assert not reader_account.has_bundled_password()


def test_bundled_password_is_used_when_nothing_is_stored(monkeypatch):
    _bundle(monkeypatch)
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    calls = []
    monkeypatch.setattr(
        win32wnet, "WNetAddConnection2", lambda *a: calls.append((a[2], a[1]))
    )
    assert share_connection.connect_status_share(r"\\NB12KI\RDP-Status")[0]
    assert calls == [(r"NB12KI\PortalLeser", RELEASE_SECRET)]


def test_stored_password_is_tried_after_a_refused_bundled_one(monkeypatch):
    """A machine set up by hand keeps working even though the release disagrees."""
    _bundle(monkeypatch)
    monkeypatch.setattr(
        share_connection, "stored_reader_credentials", lambda: ("PortalLeser", "local-secret")
    )
    attempts = []

    def connect(resource, password, username, flags):
        attempts.append(password)
        if password == RELEASE_SECRET:
            raise pywintypes.error(1326, "WNetAddConnection2", "falsches Kennwort")

    monkeypatch.setattr(win32wnet, "WNetAddConnection2", connect)
    success, _ = share_connection.connect_status_share(r"\\NB12KI\RDP-Status")
    assert success
    assert attempts == [RELEASE_SECRET, "local-secret"]


def test_identical_stored_and_bundled_password_is_tried_once(monkeypatch):
    _bundle(monkeypatch)
    monkeypatch.setattr(
        share_connection, "stored_reader_credentials", lambda: ("PortalLeser", RELEASE_SECRET)
    )
    attempts = []
    monkeypatch.setattr(
        win32wnet, "WNetAddConnection2", lambda *a: attempts.append(a[1])
    )
    share_connection.connect_status_share(r"\\NB12KI\RDP-Status")
    assert attempts == [RELEASE_SECRET]


def test_stored_account_outranks_the_bundled_one_for_display(monkeypatch):
    _bundle(monkeypatch)
    monkeypatch.setattr(
        share_connection, "stored_reader_credentials", lambda: ("Sonderleser", "x")
    )
    assert share_connection.load_reader_credentials() == ("Sonderleser", "x")
    assert share_connection.reader_account_name() == "Sonderleser"
    assert share_connection.reader_account_source() == "stored"


def test_reader_source_names_where_the_account_came_from(monkeypatch):
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    assert share_connection.reader_account_source() == "none"
    _bundle(monkeypatch)
    assert share_connection.reader_account_source() == "bundled"
    assert share_connection.reader_account_name() == "PortalLeser"


def test_without_any_account_windows_uses_what_it_already_has(monkeypatch):
    """Not passing credentials is how a share set up through the dialog stays usable."""
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    calls = []
    monkeypatch.setattr(
        win32wnet, "WNetAddConnection2", lambda *a: calls.append((a[1], a[2]))
    )
    share_connection.connect_status_share(r"\\NB12KI\RDP-Status")
    assert calls == [(None, None)]


def test_wizard_hides_credentials_when_the_release_brings_an_account(qtbot, monkeypatch):
    _bundle(monkeypatch)
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    page = wizard.page(MachineRegistrationWizard.SCAN_PAGE)
    page.credentials.load_account()
    assert not page.credentials.isVisible()
    assert "bringt ein Lesekonto mit" in page.credentials.hint.text()
    # An agent that answers but cannot be read is what the fields are for.
    page._on_found(AgentProbe("192.168.2.91", agent_present=True, message="nicht lesbar"))
    page._on_finished(1)
    assert page.credentials.isVisibleTo(page)


def test_wizard_asks_at_once_when_there_is_no_account_at_all(qtbot, monkeypatch):
    from portal_app.services import reader_account

    monkeypatch.setattr(reader_account, "BUNDLED_READER_PASSWORD", "")
    monkeypatch.setattr(share_connection, "stored_reader_credentials", lambda: None)
    wizard = MachineRegistrationWizard()
    qtbot.addWidget(wizard)
    page = wizard.page(MachineRegistrationWizard.SCAN_PAGE)
    page.credentials.load_account()
    assert page.credentials.isVisibleTo(page)
    assert page.credentials.user.text() == "PortalLeser"
