"""Main window for the locally testable Kirschke RDP portal."""

from __future__ import annotations

import logging
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.active_directory_sync import (
    check_active_directory_readiness,
    sync_rdp_group_members,
)
from portal_app.services.admin_security import (
    AdminLockoutError,
    LocalAdminPasswordStore,
    directory_mode,
)
from portal_app.services.agent_identity import machine_hostnames
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.services.directory_users import discover_windows_domain_accounts
from portal_app.services.fallback_scanning import FallbackScanner
from portal_app.services.live_status_polling import AutomaticLiveStatusPoller
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.local_store import LocalStore, StoreConflictError
from portal_app.services.reservation_access import apply_reservations
from portal_app.services.windows_admin_auth import (
    check_windows_admin_authorization,
    test_password_fallback_allowed,
)
from portal_app.ui.design import Typography
from portal_app.ui.icons import kirschke_window_icon
from portal_app.ui.widgets.machine_registration_wizard import MachineRegistrationWizard
from portal_app.ui.widgets.management_pages import AdministrationWidget, SettingsWidget
from portal_app.ui.widgets.rdp_access_dialog import RDPAccessDialog
from portal_app.ui.widgets.reservation_calendar import ReservationCalendarWidget
from portal_app.ui.widgets.session_log import SessionLogWidget
from portal_app.ui.widgets.user_settings_dialog import UserSettingsDialog
from portal_app.ui.widgets.workstation_cards import WorkstationCardsWidget
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.workstation_dialog import WorkstationDialog
from portal_app.version import PORTAL_VERSION
from shared.agent_paths import expand_directory
from shared.enums import EventResult, EventSource, EventType, ManualFlagType
from shared.session_identity import is_active_session, is_console_session, session_username

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Card dashboard, editing forms and calendar backed by local test data."""

    workstation_selected = Signal(Workstation)
    refresh_requested = Signal()

    PAGE_MACHINES = 0
    PAGE_CALENDAR = 1
    PAGE_LOGS = 2
    PAGE_ADMIN = 3
    PAGE_SETTINGS = 4
    PAGE_DETAIL = 5

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        automatic_live_status: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Kirschke · RDP Portal {PORTAL_VERSION}")
        self._automatic_live_status_enabled = automatic_live_status
        self.logo_path = Path(__file__).resolve().parent / "assets" / "kirschke_logo.png"
        self.setWindowIcon(kirschke_window_icon())
        self.setMinimumSize(QSize(1080, 720))
        self.resize(1360, 860)

        self.store = LocalStore()
        self.directory_mode = directory_mode()
        self.local_admin_password_store = LocalAdminPasswordStore()
        self.agent_status_service = LocalAgentStatusService(
            directory=self.store.agent_status_directory
        )
        self.live_status_poller = AutomaticLiveStatusPoller(max_parallel=4, parent=self)
        self.fallback_scanner = FallbackScanner(parent=self)
        self.fallback_scanner.completed.connect(self._on_fallback_scan_completed)
        self.workstations: list[Workstation] = []
        self.reservations: list[Reservation] = []
        self.session_events: list[SessionEvent] = []
        self.current_user = detect_initial_user(MockUser.create_user())
        self.nav_buttons: list[QPushButton] = []
        self._admin_unlocked = False
        self._pending_save = False
        # Set by a non-blocking poll whose reservation change still needs a view
        # refresh once the background folder scan delivers.
        self._reservation_change_pending = False
        self._load_data()
        self._create_ui()
        self._update_storage_status("Gemeinsamer Speicher bereit")
        self._connect_signals()
        self._apply_theme()
        # A crash or "End task" skips the cleanup in closeEvent, and the leftover
        # .rdp files name the target machine and the user.
        self._cleanup_stale_rdp_files()
        self.rdp_poll_timer = QTimer(self)
        self.rdp_poll_timer.setInterval(1500)
        self.rdp_poll_timer.timeout.connect(self._poll_rdp_sessions)
        self.rdp_poll_timer.start()
        self._poll_rdp_sessions()
        self.agent_poll_timer = QTimer(self)
        self.agent_poll_timer.setInterval(self.store.status_refresh_interval * 1000)
        self.agent_poll_timer.timeout.connect(self._scheduled_status_update)
        self.agent_poll_timer.start()
        self._poll_agent_status()
        if self._automatic_live_status_enabled:
            QTimer.singleShot(0, lambda: self._run_status_update_cycle(force=True))
        self.shared_store_sync_timer = QTimer(self)
        self.shared_store_sync_timer.setInterval(5000)
        self.shared_store_sync_timer.timeout.connect(self._sync_shared_store)
        self.shared_store_sync_timer.start()

    def _load_data(self) -> None:
        fallback = []  # A new pilot must not offer fictitious targets as real PCs.
        self.workstations, self.current_user, self.reservations = self.store.load(fallback, self.current_user)
        self._apply_local_agent_fallbacks()
        self.session_events = self.store.load_events()
        self.directory_accounts = self.store.load_directory_accounts()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        if not self.store.path.exists():
            self.store.save(self._saved_workstations, self._saved_user, self.reservations, self.store.theme_mode)
        self.store.initialize_event_log()

    def _apply_local_agent_fallbacks(self) -> None:
        """Attach client-local fallback paths to freshly loaded shared machines."""
        for workstation in self.workstations:
            directory, explicit = self.store.get_workstation_agent_status_directory(
                workstation.workstation_id
            )
            workstation.agent_fallback_directory = str(directory)
            workstation.agent_fallback_is_explicit = explicit

    def _create_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("appBackground")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(34, 26, 34, 26)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("appShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self._create_header())
        shell_layout.addWidget(self._create_navigation())
        shell_layout.addWidget(self._create_content(), 1)
        outer.addWidget(shell)

    def _create_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(36, 22, 36, 18)
        layout.setSpacing(14)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("brandLogo")
        self.logo_label.setFixedSize(285, 48)
        layout.addWidget(self.logo_label)
        self._update_logo()
        product = QLabel(f"RDP PORTAL · TEST {PORTAL_VERSION}")
        product.setObjectName("productName")
        layout.addWidget(product)
        layout.addStretch()
        self.user_button = QPushButton()
        self.user_button.setObjectName("userButton")
        self.user_button.setCursor(Qt.PointingHandCursor)
        self.user_button.clicked.connect(self._edit_user)
        layout.addWidget(self.user_button)
        self.avatar_button = QPushButton()
        self.avatar_button.setObjectName("avatarButton")
        self.avatar_button.setFixedSize(42, 42)
        self.avatar_button.setCursor(Qt.PointingHandCursor)
        self.avatar_button.clicked.connect(self._edit_user)
        layout.addWidget(self.avatar_button)
        self._update_user_header()
        return header

    def _create_navigation(self) -> QWidget:
        navigation = QWidget()
        navigation.setObjectName("navigation")
        layout = QHBoxLayout(navigation)
        layout.setContentsMargins(28, 0, 28, 0)
        layout.setSpacing(4)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        labels = ("Maschinen", "Kalender", "Logs", "Admin", "Einstellungen")
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setProperty("pageIndex", index)
            button.setChecked(index == self.PAGE_MACHINES)
            self.nav_group.addButton(button)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        return navigation

    def _create_content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 26, 36, 30)
        layout.setSpacing(16)
        self.page_eyebrow = QLabel("ARBEITSPLATZÜBERSICHT")
        self.page_eyebrow.setObjectName("eyebrow")
        layout.addWidget(self.page_eyebrow)
        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.page_title = QLabel("Maschinen")
        self.page_title.setObjectName("pageTitle")
        self.page_title.setFont(Typography.heading_1())
        title_box.addWidget(self.page_title)
        self.page_subtitle = QLabel("Verfügbare Arbeitsplätze und aktive Sitzungen auf einen Blick.")
        self.page_subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(self.page_subtitle)
        title_row.addLayout(title_box)
        title_row.addStretch()
        self.summary = QLabel()
        self.summary.setObjectName("summaryBadge")
        self._update_summary()
        title_row.addWidget(self.summary, alignment=Qt.AlignBottom)
        layout.addLayout(title_row)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.overview_view = WorkstationCardsWidget(self.workstations, self.current_user, self)
        self.stack.addWidget(self.overview_view)
        self.calendar_view = ReservationCalendarWidget(
            self.workstations, list(self.reservations), self.current_user, self
        )
        self.stack.addWidget(self.calendar_view)
        self.session_log_view = SessionLogWidget([], self.current_user, self)
        self.session_log_view.set_events(self.session_events)
        self.stack.addWidget(self.session_log_view)
        self.admin_view = AdministrationWidget(self.workstations, self)
        self.admin_view.set_storage_directory(str(self.store.directory))
        self.admin_view.set_directory_mode(self.directory_mode)
        self.stack.addWidget(self.admin_view)
        self.settings_view = SettingsWidget(
            self.current_user,
            theme_mode=self.theme_mode,
            dark_mode=self.dark_mode,
            status_refresh_interval=self.store.status_refresh_interval,
            parent=self,
        )
        self.stack.addWidget(self.settings_view)
        self.detail_view = WorkstationDetailWidget(self.current_user, self)
        self.stack.addWidget(self.detail_view)
        layout.addWidget(self.stack, 1)
        return content

    def _connect_signals(self) -> None:
        self.nav_group.buttonClicked.connect(self._on_navigation_clicked)
        self.overview_view.workstation_selected.connect(self.on_workstation_selected)
        self.overview_view.connect_requested.connect(self.on_connect_requested)
        self.overview_view.logoff_requested.connect(self._logoff_session)
        self.overview_view.account_selected.connect(self._select_login_account)
        self.overview_view.account_add_requested.connect(self._add_login_account)
        self.overview_view.add_requested.connect(self._add_workstation)
        self.overview_view.refresh_requested.connect(self.on_refresh)
        self.overview_view.agent_diagnostics_requested.connect(self._show_agent_diagnostics)
        self.admin_view.add_requested.connect(self._add_workstation)
        self.admin_view.edit_requested.connect(self._edit_workstation)
        self.admin_view.force_disconnect_requested.connect(self._force_disconnect_workstation)
        self.admin_view.force_logoff_requested.connect(self._admin_logoff_workstation)
        self.admin_view.delete_requested.connect(self._delete_workstation)
        self.admin_view.rdp_access_requested.connect(self._manage_rdp_access)
        self.admin_view.lock_requested.connect(self._lock_admin)
        self.admin_view.storage_directory_requested.connect(self._change_storage_directory)
        self.admin_view.active_directory_status_requested.connect(self._update_active_directory_status)
        self.admin_view.admin_password_change_requested.connect(self._change_local_admin_password)
        self.settings_view.edit_user_requested.connect(self._edit_user)
        self.settings_view.agent_refresh_requested.connect(
            lambda: self._run_status_update_cycle(force=True)
        )
        self.settings_view.theme_changed.connect(self._set_theme_mode)
        self.settings_view.status_refresh_interval_changed.connect(
            self._set_status_refresh_interval
        )
        self.calendar_view.reservations_changed.connect(self._on_reservations_changed)
        self.detail_view.back_requested.connect(self._show_machines)
        self.detail_view.edit_requested.connect(self._edit_workstation)
        self.detail_view.connect_requested.connect(self.on_connect_requested)
        self.detail_view.logoff_requested.connect(self._logoff_session)
        self.detail_view.live_status_requested.connect(self._query_live_status)
        self.detail_view.account_selected.connect(self._select_login_account)
        self.detail_view.account_add_requested.connect(self._add_login_account)
        self.detail_view.diagnostics_requested.connect(self._run_rdp_diagnostics)
        self.detail_view.agent_assignment_requested.connect(self._assign_agent)
        self.detail_view.fallback_setup_requested.connect(self._setup_workstation_fallback)
        self.detail_view.workstation_updated.connect(self._on_workstation_updated)
        self.workstation_selected.connect(self.detail_view.set_workstation)
        self.live_status_poller.succeeded.connect(self._on_live_status_succeeded)
        self.live_status_poller.failed.connect(self._on_live_status_failed)

    @Slot(Workstation, str)
    def _select_login_account(self, workstation: Workstation, account: str) -> None:
        if account and account not in workstation.login_accounts + workstation.session_accounts():
            return
        try:
            self.store.save_login_selection(workstation.workstation_id, account, self._saved_user)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Anmeldekonto nicht gespeichert", str(exc))
        else:
            workstation.selected_login_account = account or None
        self._refresh_login_views(workstation)

    def _refresh_login_views(self, workstation: Workstation) -> None:
        self._refresh_workstation_views()
        if self.detail_view.workstation and self.detail_view.workstation.workstation_id == workstation.workstation_id:
            self.detail_view.set_workstation(workstation)

    @Slot(Workstation)
    def _add_login_account(self, workstation: Workstation) -> None:
        from shared.login_accounts import normalize_login_accounts

        account, accepted = QInputDialog.getText(
            self, "Anmeldekonto hinzufügen",
            f"Bestehendes Windows-Konto für {workstation.display_name}:\n"
            "Zum Beispiel ZIELPC\\benutzer, DOMÄNE\\benutzer oder benutzer@firma.de.\n"
            "Es wird nur der Kontoname hinterlegt; kein Windows-Konto angelegt und kein Kennwort gespeichert.",
        )
        if not accepted:
            return
        # A timer may have refreshed the inventory while the modal dialog was open.
        workstation = next((ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id), None)
        if workstation is None:
            QMessageBox.warning(self, "Maschine nicht mehr vorhanden", "Bitte die Maschinenübersicht aktualisieren.")
            return
        try:
            accounts = normalize_login_accounts(workstation.login_accounts + [account])
            if len(accounts) > 100:
                raise ValueError("Pro Maschine können höchstens 100 Anmeldekonten hinterlegt werden.")
        except ValueError as exc:
            QMessageBox.warning(self, "Ungültiges Anmeldekonto", str(exc))
            return
        previous = list(workstation.login_accounts)
        saved_before = deepcopy(self._saved_workstations)
        workstation.login_accounts = accounts
        saved = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        if saved is None:
            QMessageBox.warning(self, "Maschine zuerst speichern", "Bitte die Maschinenstammdaten zuerst speichern.")
            workstation.login_accounts = previous
            return
        saved.login_accounts = accounts
        if not self._persist():
            workstation.login_accounts = previous
            self._saved_workstations = saved_before
            self._refresh_login_views(workstation)
            return
        selected = next(value for value in accounts if value.casefold() == account.strip().casefold())
        self._select_login_account(workstation, selected)

    @Slot(Workstation)
    def _assign_agent(self, workstation: Workstation) -> None:
        from shared.agent_snapshot import load_agent_snapshots

        try:
            snapshots = load_agent_snapshots(self.agent_status_service.directory_for(workstation))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Agent-Zuordnung", str(exc))
            return
        newest = {}
        for snapshot in snapshots:
            key = snapshot.workstation_id.strip().casefold()
            if key not in newest or snapshot.observed_at_utc > newest[key].observed_at_utc:
                newest[key] = snapshot
        choices = {"Automatisch über Maschinen-ID / Hostname": None}
        for snapshot in sorted(newest.values(), key=lambda item: item.workstation_id.casefold()):
            choices[f"{snapshot.workstation_id} · {snapshot.hostname} · Meldung {snapshot.observed_at_utc.astimezone():%d.%m. %H:%M:%S}"] = snapshot.workstation_id.strip()
        current = next((i for i, value in enumerate(choices.values())
                        if value and value.casefold() == (workstation.agent_workstation_id or "").casefold()), 0)
        choice, accepted = QInputDialog.getItem(
            self, f"Agent für {workstation.display_name} zuordnen",
            "Den Agenten dieses Zielrechners auswählen.\nDie RDP-Adresse und bestehende Reservierungen bleiben erhalten.",
            list(choices), current, False,
        )
        if not accepted:
            return
        workstation = next((ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id), None)
        if workstation is None:
            return
        selected = choices[choice]
        expected = (selected or workstation.workstation_id).casefold()
        if any(ws is not workstation and (ws.agent_workstation_id or ws.workstation_id).strip().casefold() == expected
               for ws in self.workstations):
            QMessageBox.warning(self, "Agent bereits zugeordnet", "Dieser Agent ist bereits einer anderen Maschine zugeordnet.")
            return
        saved = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        if saved is None:
            QMessageBox.warning(self, "Maschine zuerst speichern", "Bitte zuerst die Maschinenstammdaten speichern.")
            return
        previous, saved_previous = workstation.agent_workstation_id, saved.agent_workstation_id
        workstation.agent_workstation_id = saved.agent_workstation_id = selected
        if not self._persist():
            workstation.agent_workstation_id, saved.agent_workstation_id = previous, saved_previous
            return
        self._poll_agent_status()
        self.detail_view.set_workstation(workstation)

    @Slot(Workstation)
    def _setup_workstation_fallback(self, workstation: Workstation) -> None:
        from portal_app.ui.widgets.share_setup_dialog import ShareSetupDialog

        try:
            target, _ = workstation.get_connection_target()
        except ValueError:
            target = workstation.hostname
        server = (workstation.hostname or target or workstation.display_name).split(".", 1)[0]
        # Do not prefill a machine with the former global fallback.  Its server
        # and the machine-local PortalLeser account can otherwise be mixed (for
        # example Remote-Ettlingen as server with NB12KI as account).  Only a
        # path explicitly saved for this machine is safe to offer again.
        current = (
            workstation.agent_fallback_directory or ""
            if workstation.agent_fallback_is_explicit
            else ""
        )
        dialog = ShareSetupDialog(
            current,
            self,
            suggested_path=fr"\\{server}\RDP-Status",
            suggested_username=fr"{server}\PortalLeser",
            workstation_name=workstation.display_name,
        )
        self.agent_poll_timer.stop()
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            path = self.store.set_workstation_agent_status_directory(
                workstation.workstation_id,
                dialog.connected_path,
            )
            workstation.agent_fallback_directory = str(path)
            workstation.agent_fallback_is_explicit = True
            self._poll_agent_status()
            self.detail_view.set_workstation(workstation)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Datei-Fallback nicht gespeichert", str(exc))
        finally:
            self.agent_poll_timer.start()
            dialog.deleteLater()

    @staticmethod
    def _cleanup_stale_rdp_files() -> None:
        """Remove .rdp files an earlier run could not delete."""
        from portal_app.rdp import cleanup_old_rdp_files

        try:
            removed = cleanup_old_rdp_files(older_than_hours=24)
        except OSError as exc:
            logger.warning("Alte RDP-Dateien konnten nicht entfernt werden: %s", exc)
            return
        if removed:
            logger.info("%s verwaiste RDP-Datei(en) aus dem Temp-Ordner entfernt", removed)

    @Slot()
    def _poll_rdp_sessions(self) -> None:
        """Record closed RDP clients without adding a persistent visual notice."""
        from portal_app.rdp import consume_finished_rdp_sessions

        finished = consume_finished_rdp_sessions()
        for session in finished:
            workstation = next(
                (item for item in self.workstations if item.workstation_id == session.workstation_id),
                None,
            )
            if workstation:
                self._record_event(
                    workstation,
                    EventType.RDP_DISCONNECT,
                    EventResult.SUCCESS,
                    "Lokales RDP-Fenster geschlossen",
                )

    @Slot()
    def _poll_agent_status(self, *, blocking: bool = True) -> None:
        """Refresh reservations and the agent file fallback.

        ``blocking`` reads the fallback folders inline and is what startup,
        explicit user actions and the tests rely on.  The recurring heartbeat
        passes ``blocking=False``: reading a UNC path can stall for the SMB
        timeout, which must never happen on the Qt main thread, so the read goes
        to ``FallbackScanner`` and the result arrives in
        ``_on_fallback_scan_completed``.
        """
        reservation_changed = apply_reservations(self.workstations, self.reservations, self.current_user.upn)
        if reservation_changed:
            self._refresh_workstation_views()
        try:
            self.agent_status_service.set_directory(self.store.agent_status_directory)
            directories = self.agent_status_service.fallback_directories(self.workstations)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)
            return
        if not blocking:
            self._reservation_change_pending = self._reservation_change_pending or reservation_changed
            # A scan that is still running will deliver on its own; queuing a
            # second one would only build a backlog behind a slow share.
            self.fallback_scanner.request(directories)
            return
        try:
            scans = self.agent_status_service.scan_directories(directories)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)
            return
        self._apply_fallback_scans(scans, reservation_changed)

    def _report_agent_status_failure(self, exc: Exception) -> None:
        self._update_storage_status(f"Agent-Status nicht lesbar: {exc}")
        self.settings_view.agent_status.setText(f"Agent-Status nicht lesbar: {exc}")
        self.settings_view.set_agent_report(f"RDP-Portal {PORTAL_VERSION}\nKonfiguration: {self.store.agent_config_path}\nFehler: {exc}")
        self.overview_view.agent_channel_status.setText("Agent-Status nicht lesbar · Agent-Diagnose öffnen")

    @Slot(object)
    def _on_fallback_scan_completed(self, scans: object) -> None:
        """Apply a background folder scan on the UI thread."""
        reservation_changed = self._reservation_change_pending
        self._reservation_change_pending = False
        try:
            self._apply_fallback_scans(scans, reservation_changed)
        except (OSError, ValueError) as exc:
            self._report_agent_status_failure(exc)

    def _apply_fallback_scans(self, scans: object, reservation_changed: bool) -> None:
        changed = self.agent_status_service.apply_scans(self.workstations, scans)
        self.settings_view.set_agent_bridge_status(
            self.agent_status_service.last_match_count,
            self.agent_status_service.last_snapshot_count,
            self.agent_status_service.directory_summary,
            self.agent_status_service.last_errors,
        )
        service = self.agent_status_service
        self.settings_view.set_agent_report(service.last_report + f"\nPortalprogramm: {Path(sys.executable).resolve()}\nInventar: {self.store.path}\nKonfiguration: {self.store.agent_config_path}")
        checked = service.last_checked_at.astimezone().strftime("%H:%M:%S")
        live_count = sum(ws.agent_status_source == "live" and not ws.agent_live_error for ws in self.workstations)
        fallback_count = sum(ws.agent_status_source == "file" for ws in self.workstations)
        result = (
            f"Live {live_count} · Datei-Fallback {fallback_count} · "
            f"{service.last_match_count}/{len(self.workstations)} Maschinen zugeordnet"
        )
        if service.last_errors:
            result += " · Lesefehler"
        self.overview_view.agent_channel_status.setText(
            f"Automatisch alle {self.store.status_refresh_interval} s · Prüfung {checked}: {result}"
        )
        self.overview_view.agent_channel_status.setToolTip(service.directory_summary)
        if not changed and not reservation_changed:
            return
        # Heartbeats are transient. They must not save unsaved form changes or
        # cause competing writes to the shared machine configuration.
        self._refresh_workstation_views()
        if self.detail_view.workstation is not None:
            selected = next((ws for ws in self.workstations if ws.workstation_id == self.detail_view.workstation.workstation_id), None)
            if selected is not None:
                self.detail_view.set_workstation(selected)

    @Slot()
    def _scheduled_status_update(self) -> None:
        """Recurring heartbeat: never read the fallback folders on this thread."""
        if self._automatic_live_status_enabled:
            self._run_status_update_cycle(blocking=False)
        else:
            self._poll_agent_status(blocking=False)

    @Slot()
    def _run_status_update_cycle(
        self,
        workstations: list[Workstation] | None = None,
        *,
        force: bool = False,
        blocking: bool = True,
    ) -> None:
        """Refresh file fallback, then start bounded direct status requests."""
        self._poll_agent_status(blocking=blocking)
        targets = self.workstations if workstations is None else workstations
        started = self.live_status_poller.request_many(
            targets,
            self.store.status_refresh_interval,
            force=force,
        )
        if started:
            self.overview_view.agent_channel_status.setText(
                f"Live-Status wird für {started} Maschine(n) im Hintergrund aktualisiert …"
            )

    @Slot(str, object, object, int)
    def _on_live_status_succeeded(
        self,
        workstation_id: str,
        route: object,
        snapshot: object,
        elapsed: int,
    ) -> None:
        workstation = next(
            (item for item in self.workstations if item.workstation_id == workstation_id),
            None,
        )
        if workstation is None:
            return
        try:
            if workstation.get_agent_status_target() != route:
                return
            self.agent_status_service.accept_live_snapshot(workstation, snapshot, elapsed)
        except ValueError as exc:
            self.agent_status_service.record_live_failure(workstation, str(exc))
        self._poll_agent_status()

    @Slot(str, object, str)
    def _on_live_status_failed(
        self,
        workstation_id: str,
        route: object,
        message: str,
    ) -> None:
        workstation = next(
            (item for item in self.workstations if item.workstation_id == workstation_id),
            None,
        )
        if workstation is None:
            return
        if route is not None:
            try:
                if workstation.get_agent_status_target() != route:
                    return
            except ValueError:
                return
        self.agent_status_service.record_live_failure(workstation, message)
        self._poll_agent_status()

    @Slot(int)
    def _set_status_refresh_interval(self, seconds: int) -> None:
        try:
            seconds = self.store.save_status_refresh_interval(seconds, self._saved_user)
        except (OSError, ValueError) as exc:
            self.settings_view.set_status_refresh_interval(
                self.store.status_refresh_interval
            )
            QMessageBox.warning(self, "Statusintervall nicht gespeichert", str(exc))
            return
        self.agent_poll_timer.setInterval(seconds * 1000)
        self.live_status_poller.set_interval(seconds)
        self._run_status_update_cycle(force=True)

    @Slot()
    def _show_agent_diagnostics(self) -> None:
        self.nav_buttons[self.PAGE_SETTINGS].setChecked(True)
        self._on_navigation_clicked(self.nav_buttons[self.PAGE_SETTINGS])
        self.settings_view.scroll.verticalScrollBar().setValue(0)
        self._poll_agent_status()

    def _on_navigation_clicked(self, button: QPushButton) -> None:
        page_index = int(button.property("pageIndex"))
        if page_index == self.PAGE_ADMIN and not self._admin_unlocked:
            if not self._request_admin_access():
                current_page = self.stack.currentIndex()
                fallback_page = current_page if 0 <= current_page < self.PAGE_DETAIL else self.PAGE_MACHINES
                self.nav_buttons[fallback_page].setChecked(True)
                return
        if page_index == self.PAGE_ADMIN and self.directory_mode == "active_directory":
            self._update_active_directory_status()
        self.stack.setCurrentIndex(page_index)
        pages = (
            ("ARBEITSPLATZÜBERSICHT", "Maschinen", "Verfügbare Arbeitsplätze und aktive Sitzungen auf einen Blick."),
            ("PLANUNG", "Reservierungen", "Maschinen über mehrere Tage und Zeiträume reservieren."),
            ("AKTIVITÄTEN", "Logs", "Verbindungen, Sitzungen und Systemereignisse nachvollziehen."),
            ("VERWALTUNG", "Administration", "Maschinenstammdaten zentral verwalten."),
            ("KONFIGURATION", "Einstellungen", "Allgemeine Benutzer- und RDP-Einstellungen."),
        )
        eyebrow, title, subtitle = pages[page_index]
        self.page_eyebrow.setText(eyebrow)
        self.page_title.setText(title)
        self.page_subtitle.setText(subtitle)
        self.summary.setVisible(page_index == self.PAGE_MACHINES)
        if page_index == self.PAGE_MACHINES and self._automatic_live_status_enabled:
            self._run_status_update_cycle(force=True)

    def _request_admin_access(self) -> bool:
        if self.directory_mode != "active_directory":
            return self._request_local_admin_access()
        authorization = check_windows_admin_authorization()
        if authorization.authorized:
            self._unlock_admin(f"Admin per Windows-Gruppe: {authorization.group_name}")
            return True
        if not test_password_fallback_allowed():
            QMessageBox.warning(
                self,
                "Admin-Zugang verweigert",
                f"{authorization.message}\n\nDie lokale Testfreigabe ist deaktiviert.",
            )
            return False
        return self._request_local_admin_access()

    def _request_local_admin_access(self) -> bool:
        if not self.local_admin_password_store.is_configured():
            return self._configure_local_admin_password()
        password, accepted = QInputDialog.getText(
            self,
            "Admin-Zugang",
            "Lokales Admin-Passwort:",
            QLineEdit.Password,
        )
        if not accepted:
            return False
        try:
            correct = self.local_admin_password_store.verify_password(password)
        except AdminLockoutError as exc:
            QMessageBox.warning(self, "Adminzugang gesperrt", str(exc))
            return False
        if not correct:
            QMessageBox.warning(self, "Zugriff verweigert", "Das eingegebene Admin-Passwort ist nicht korrekt.")
            return False
        self._unlock_admin("Lokales Admin-Passwort bestätigt")
        return True

    def _configure_local_admin_password(self) -> bool:
        password, accepted = QInputDialog.getText(
            self,
            "Admin-Passwort einrichten",
            "Noch kein lokales Admin-Passwort eingerichtet. Neues Passwort (mindestens 10 Zeichen):",
            QLineEdit.Password,
        )
        if not accepted:
            return False
        confirmation, confirmed = QInputDialog.getText(
            self,
            "Admin-Passwort bestätigen",
            "Neues Admin-Passwort wiederholen:",
            QLineEdit.Password,
        )
        if not confirmed:
            return False
        if password != confirmation:
            QMessageBox.warning(self, "Passwörter stimmen nicht überein", "Bitte die Einrichtung erneut starten.")
            return False
        try:
            self.local_admin_password_store.set_password(password)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Admin-Passwort ungültig", str(exc))
            return False
        self._unlock_admin("Lokales Admin-Passwort eingerichtet")
        return True

    def _change_local_admin_password(self) -> None:
        if self.directory_mode == "active_directory" or not self._admin_unlocked:
            return
        current, accepted = QInputDialog.getText(
            self,
            "Admin-Passwort ändern",
            "Aktuelles lokales Admin-Passwort:",
            QLineEdit.Password,
        )
        if not accepted:
            return
        try:
            correct = self.local_admin_password_store.verify_password(current)
        except AdminLockoutError as exc:
            QMessageBox.warning(self, "Adminzugang gesperrt", str(exc))
            return
        if not correct:
            QMessageBox.warning(self, "Zugriff verweigert", "Das aktuelle Admin-Passwort ist nicht korrekt.")
            return
        new_password, accepted = QInputDialog.getText(
            self,
            "Admin-Passwort ändern",
            "Neues lokales Admin-Passwort (mindestens 10 Zeichen):",
            QLineEdit.Password,
        )
        if not accepted:
            return
        confirmation, confirmed = QInputDialog.getText(
            self,
            "Admin-Passwort bestätigen",
            "Neues Admin-Passwort wiederholen:",
            QLineEdit.Password,
        )
        if not confirmed:
            return
        if new_password != confirmation:
            QMessageBox.warning(self, "Passwörter stimmen nicht überein", "Das Passwort wurde nicht geändert.")
            return
        try:
            self.local_admin_password_store.set_password(new_password)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Admin-Passwort ungültig", str(exc))
            return
        QMessageBox.information(self, "Admin-Passwort geändert", "Das lokale Admin-Passwort wurde aktualisiert.")

    def _unlock_admin(self, access_label: str) -> None:
        self._admin_unlocked = True
        self.admin_view.set_access_status(True, access_label)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin · offen")

    def _lock_admin(self) -> None:
        self._admin_unlocked = False
        self.admin_view.set_access_status(False)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin")
        self._show_machines()

    @Slot()
    def _update_active_directory_status(self) -> None:
        readiness = check_active_directory_readiness()
        self.admin_view.set_active_directory_status(readiness.message)

    @Slot(str)
    def _change_agent_directory(self, directory: str) -> None:
        try:
            self.store.set_agent_status_directory(directory)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Agent-Statusordner nicht gespeichert", str(exc))
            return
        self._apply_local_agent_fallbacks()
        self._poll_agent_status()

    @Slot(str)
    def _change_storage_directory(self, directory: str) -> None:
        target = expand_directory(directory)
        if target.name.casefold() in {"agent-status", "agenten-status"}:
            QMessageBox.warning(
                self,
                "Kein Inventarordner",
                "Ein Agent-Statusordner ist kein Inventar-Speicherort. "
                "Den Datei-Fallback in den Details der betreffenden Maschine einrichten.",
            )
            return
        try:
            self.store.relocate(target, move_files=True)
            self.agent_status_service.set_directory(self.store.agent_status_directory)
            self.admin_view.set_storage_directory(str(self.store.directory))
            self._persist()
            self._update_storage_status("Speicherort gewechselt")
            self._poll_agent_status()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "Speicherort konnte nicht geändert werden",
                f"Die Dateien wurden nicht vollständig verschoben:\n{exc}",
            )
            return
        QMessageBox.information(
            self,
            "Speicherort geändert",
            f"Status und Ereignislog werden jetzt gespeichert unter:\n{self.store.directory}",
        )

    @Slot(Workstation)
    def on_workstation_selected(self, workstation: Workstation) -> None:
        self.workstation_selected.emit(workstation)
        events = [
            event for event in self.session_events if event.workstation_id == workstation.workstation_id
        ]
        self.detail_view.set_session_events(events)
        self.stack.setCurrentIndex(self.PAGE_DETAIL)
        self.page_eyebrow.setText("MASCHINENDETAILS")
        self.page_title.setText(workstation.display_name)
        self.page_subtitle.setText(workstation.get_connection_target_display())
        self.summary.setVisible(False)

    def _show_machines(self) -> None:
        self.nav_buttons[self.PAGE_MACHINES].setChecked(True)
        self._on_navigation_clicked(self.nav_buttons[self.PAGE_MACHINES])

    def _next_workstation_id(self) -> str:
        numbers = []
        for ws in self.workstations:
            try:
                numbers.append(int(ws.workstation_id.rsplit("-", 1)[-1]))
            except ValueError:
                continue
        return f"WS-{max(numbers, default=0) + 1:03d}"

    def _add_workstation(self) -> None:
        wizard = MachineRegistrationWizard(parent=self)
        if wizard.exec() != QDialog.Accepted:
            return
        dialog = WorkstationDialog(
            suggested_id=self._next_workstation_id(),
            prefill=wizard.prefill,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted or not dialog.workstation:
            return
        if any(ws.workstation_id == dialog.workstation.workstation_id for ws in self.workstations):
            QMessageBox.warning(self, "Doppelte ID", "Diese Maschinen-ID ist bereits vergeben.")
            return
        fallback, explicit = self.store.get_workstation_agent_status_directory(
            dialog.workstation.workstation_id
        )
        dialog.workstation.agent_fallback_directory = str(fallback)
        dialog.workstation.agent_fallback_is_explicit = explicit
        self.workstations.append(dialog.workstation)
        self._refresh_workstation_views()
        if dialog.should_save:
            self._commit_workstation(dialog.workstation)
            self._persist()

    @Slot(Workstation)
    def _edit_workstation(self, workstation: Workstation) -> None:
        dialog = WorkstationDialog(workstation=workstation, parent=self)
        if dialog.exec() != QDialog.Accepted or not dialog.workstation:
            return
        dialog.workstation.agent_fallback_directory = workstation.agent_fallback_directory
        dialog.workstation.agent_fallback_is_explicit = workstation.agent_fallback_is_explicit
        index = self.workstations.index(workstation)
        self.workstations[index] = dialog.workstation
        self._refresh_workstation_views()
        if self.stack.currentIndex() == self.PAGE_DETAIL:
            self.on_workstation_selected(dialog.workstation)
        if dialog.should_save:
            self._commit_workstation(dialog.workstation)
            self._persist()

    @Slot(Workstation)
    def _on_workstation_updated(self, workstation: Workstation) -> None:
        previous = next((ws for ws in self._saved_workstations if ws.workstation_id == workstation.workstation_id), None)
        flag_changed = previous is not None and (
            previous.manual_flag_type != workstation.manual_flag_type
            or previous.manual_flag_set_at_utc != workstation.manual_flag_set_at_utc
        )
        self._refresh_workstation_views()
        self.detail_view.set_workstation(workstation)
        self._commit_workstation(workstation)
        if self._persist() and flag_changed:
            event_type = EventType.MANUAL_FLAG_CLEARED if workstation.manual_flag_type == ManualFlagType.NONE else EventType.MANUAL_FLAG_SET
            self._record_event(workstation, event_type, EventResult.SUCCESS, workstation.manual_flag_reason)

    @Slot(Workstation)
    def _force_disconnect_workstation(self, workstation: Workstation) -> None:
        from portal_app.rdp import disconnect_rdp_session, has_active_rdp_session

        if not has_active_rdp_session(workstation.workstation_id):
            QMessageBox.information(
                self,
                "Kein lokales RDP-Fenster",
                f"Für {workstation.display_name} läuft kein von diesem Portal gestartetes RDP-Fenster.\n\n"
                "Eine möglicherweise auf dem Zielrechner verbliebene Windows-Sitzung kann ohne "
                "administrativen Remotezugriff oder Agent nicht zuverlässig abgemeldet werden.",
            )
            return
        answer = QMessageBox.warning(
            self,
            "RDP-Verbindung trennen",
            f"Das RDP-Fenster für {workstation.display_name} wird sofort beendet.\n\n"
            "Die Programme auf dem Zielrechner laufen weiter; die Windows-Sitzung kann dort als "
            "„Getrennt“ angemeldet bleiben. Verbindung wirklich trennen?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self._record_event(
            workstation,
            EventType.ADMIN_DISCONNECT_REQUESTED,
            EventResult.PENDING,
            source=EventSource.ADMIN,
        )
        disconnected, failures = disconnect_rdp_session(workstation.workstation_id)
        if failures or disconnected == 0:
            self._record_event(
                workstation,
                EventType.ADMIN_DISCONNECT_FAILED,
                EventResult.FAILED,
                "Lokales RDP-Fenster konnte nicht beendet werden",
                EventSource.ADMIN,
            )
            QMessageBox.critical(
                self,
                "Trennen fehlgeschlagen",
                f"Das RDP-Fenster für {workstation.display_name} konnte nicht beendet werden.",
            )
            return
        self._record_event(
            workstation,
            EventType.ADMIN_DISCONNECT_COMPLETED,
            EventResult.SUCCESS,
            source=EventSource.ADMIN,
        )
        self._poll_rdp_sessions()
        QMessageBox.information(
            self,
            "RDP getrennt",
            f"Das lokale RDP-Fenster für {workstation.display_name} wurde beendet. "
            "Dies ist kein vollständiges Windows-Logoff.",
        )

    @Slot(Workstation)
    def _admin_logoff_workstation(self, workstation: Workstation) -> None:
        """Offer a separate emergency WTS action; Windows remains the authority."""
        from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog

        if not self._admin_unlocked:
            return
        sessions = [
            dict(item)
            for item in workstation.agent_sessions
            if is_active_session(item)
            and type(item.get("session_id")) is int
            and item["session_id"] > 0
            and item.get("login_time")
        ]
        if not sessions:
            QMessageBox.warning(
                self,
                "Keine prüfbare Sitzung",
                "Für die Notfall-Abmeldung wird eine aktuelle Agent-Meldung mit Benutzer, "
                "Sitzungsnummer und Anmeldezeit benötigt.",
            )
            return
        labels = []
        for item in sessions:
            username = session_username(item)
            labels.append(
                f"{username} · Sitzung {item['session_id']} · {item.get('session_state')} · {item['login_time']}"
            )
        selected_index = 0
        if len(sessions) > 1:
            label, accepted = QInputDialog.getItem(
                self,
                "Administrative Notfall-Abmeldung",
                "Welche Windows-Sitzung soll nach erneuter Live-Prüfung abgemeldet werden?",
                labels,
                0,
                False,
            )
            if not accepted:
                return
            selected_index = labels.index(label)
        try:
            target, _ = workstation.get_connection_target()
        except ValueError as exc:
            QMessageBox.warning(self, "Ziel fehlt", str(exc))
            return
        dialog = SessionLogoffDialog(
            target,
            workstation.display_name,
            sessions[selected_index],
            self,
            administrative=True,
            expected_agent_id=workstation.agent_workstation_id or workstation.workstation_id,
            status_target=workstation.get_agent_status_target(),
            hostnames=None if workstation.agent_workstation_id else machine_hostnames(workstation),
        )
        dialog.request_finished.connect(
            lambda success, message, ws=workstation: self._admin_logoff_finished(
                ws, success, message
            )
        )
        dialog.exec()
        dialog.deleteLater()

    def _admin_logoff_finished(
        self,
        workstation: Workstation,
        success: bool,
        message: str,
    ) -> None:
        self._record_event(
            workstation,
            EventType.ADMIN_LOGOFF_COMPLETED if success else EventType.ADMIN_LOGOFF_FAILED,
            EventResult.SUCCESS if success else EventResult.FAILED,
            message,
            EventSource.ADMIN,
        )
        if success:
            self._run_status_update_cycle([workstation], force=True)

    @Slot(Workstation)
    def _delete_workstation(self, workstation: Workstation) -> None:
        from portal_app.rdp import has_active_rdp_session

        active_note = ""
        if has_active_rdp_session(workstation.workstation_id):
            active_note = (
                "\n\nFür diese Maschine läuft noch ein lokales RDP-Fenster. "
                "Es wird durch das Löschen nicht beendet."
            )
        answer = QMessageBox.warning(
            self,
            "Maschine löschen",
            f"{workstation.display_name} ({workstation.workstation_id}) wirklich aus dem Portal entfernen?\n\n"
            "Das entfernt auch ihre Reservierungen. Die Maschine selbst und eine vorhandene "
            f"Windows-Sitzung bleiben unverändert.{active_note}",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self.workstations = [
            candidate
            for candidate in self.workstations
            if candidate.workstation_id != workstation.workstation_id
        ]
        self.reservations = [
            reservation
            for reservation in self.reservations
            if reservation.workstation_id != workstation.workstation_id
        ]
        self._saved_workstations = deepcopy(self.workstations)
        self.calendar_view.reservations = list(self.reservations)
        self._refresh_workstation_views()
        if (
            self.detail_view.workstation is not None
            and self.detail_view.workstation.workstation_id == workstation.workstation_id
        ):
            self._show_machines()
        self._persist()

    def _refresh_workstation_views(self) -> None:
        apply_reservations(self.workstations, self.reservations, self.current_user.upn)
        self.overview_view.set_workstations(self.workstations)
        self.calendar_view.set_workstations(self.workstations)
        self.admin_view.set_workstations(self.workstations)
        self._update_summary()
        if self.detail_view.workstation is not None:
            selected = next((ws for ws in self.workstations if ws.workstation_id == self.detail_view.workstation.workstation_id), None)
            if selected is not None:
                self.detail_view.set_workstation(selected)

    def _edit_user(self) -> None:
        dialog = UserSettingsDialog(self.current_user, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._update_user_header()
        self.settings_view.set_user(self.current_user)
        self.calendar_view.set_user(self.current_user)
        self.detail_view.set_user(self.current_user)
        if dialog.should_save:
            self._saved_user = deepcopy(self.current_user)
            self._persist()

    @Slot(Workstation)
    def _manage_rdp_access(self, workstation: Workstation) -> None:
        """Edit desired RDP group membership without handling any credentials."""
        lookup = discover_windows_domain_accounts()
        current_account = self.current_user.get_rdp_username() or self.current_user.upn
        known_accounts = self.directory_accounts + lookup.accounts + [current_account]
        dialog = RDPAccessDialog(workstation, known_accounts, lookup.message, self)
        if dialog.exec() != QDialog.Accepted:
            return
        previous = {account.casefold(): account for account in workstation.rdp_access_users}
        updated = {account.casefold(): account for account in dialog.selected_members}
        granted = [updated[key] for key in sorted(updated.keys() - previous.keys())]
        revoked = [previous[key] for key in sorted(previous.keys() - updated.keys())]
        self.directory_accounts = self.store.save_directory_accounts(dialog.known_accounts)
        if not granted and not revoked:
            if dialog.sync_to_active_directory:
                self._sync_rdp_access_to_active_directory(workstation)
            return
        workstation.rdp_access_users = dialog.selected_members
        self._commit_workstation(workstation)
        self._refresh_workstation_views()
        if not self._persist():
            return
        for account in granted:
            self._record_event(
                workstation,
                EventType.RDP_ACCESS_GRANTED,
                EventResult.SUCCESS,
                f"RDP-{workstation.workstation_id}: {account}",
                EventSource.ADMIN,
            )
        for account in revoked:
            self._record_event(
                workstation,
                EventType.RDP_ACCESS_REVOKED,
                EventResult.SUCCESS,
                f"RDP-{workstation.workstation_id}: {account}",
                EventSource.ADMIN,
            )
        if dialog.sync_to_active_directory:
            self._sync_rdp_access_to_active_directory(workstation)

    def _sync_rdp_access_to_active_directory(self, workstation: Workstation) -> None:
        """Apply the explicitly saved membership to one AD group after confirmation."""
        group_name = f"RDP-{workstation.workstation_id}"
        members = workstation.rdp_access_users
        preview = "\n".join(f"• {account}" for account in members) or "• Keine Benutzer (direkte Benutzer werden entfernt)"
        answer = QMessageBox.warning(
            self,
            "RDP-Gruppe in Active Directory übernehmen",
            f"Die direkten Benutzer der AD-Gruppe {group_name} werden auf diesen Stand gesetzt:\n\n{preview}\n\n"
            "Die Ausführung verwendet Ihr aktuell angemeldetes Windows-Konto. Fortfahren?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        result = sync_rdp_group_members(group_name, members)
        event_type = EventType.RDP_ACCESS_SYNC_COMPLETED if result.success else EventType.RDP_ACCESS_SYNC_FAILED
        self._record_event(workstation, event_type, EventResult.SUCCESS if result.success else EventResult.FAILED, result.message, EventSource.ADMIN)
        if result.success:
            QMessageBox.information(self, "RDP-Gruppe abgeglichen", result.message)
        else:
            QMessageBox.warning(self, "AD-Übernahme nicht möglich", result.message)

    def _update_user_header(self) -> None:
        if not hasattr(self, "user_button"):
            return
        self.user_button.setText(f"{self.current_user.display_name}\n{self.current_user.get_rdp_username() or 'RDP-Anmeldung festlegen'}")
        initials = "".join(part[0] for part in self.current_user.display_name.split()[:2]).upper() or "U"
        self.avatar_button.setText(initials)

    @staticmethod
    def _system_prefers_dark() -> bool:
        """Read the Windows app color preference, with a Qt fallback."""
        if sys.platform == "win32":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    apps_use_light_theme, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return int(apps_use_light_theme) == 0
            except OSError:
                pass
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            return False

    def _resolve_dark_mode(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        return self._system_prefers_dark()

    @Slot(str)
    def _set_theme_mode(self, theme_mode: str) -> None:
        theme_mode = theme_mode if theme_mode in {"system", "light", "dark"} else "system"
        if self.theme_mode == theme_mode:
            return
        self.theme_mode = theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._apply_theme()
        self.settings_view.set_theme_mode(theme_mode, self.dark_mode)
        self._persist()

    def _set_dark_mode(self, dark_mode: bool) -> None:
        """Compatibility helper retained for internal callers and tests."""
        self._set_theme_mode("dark" if dark_mode else "light")

    def _apply_theme(self) -> None:
        self.setStyleSheet(self._application_style(self.dark_mode))
        self._update_logo()

    def _update_logo(self) -> None:
        if not hasattr(self, "logo_label"):
            return
        pixmap = QPixmap(str(self.logo_path))
        if pixmap.isNull():
            self.logo_label.setText("KIRSCHKE")
            return
        if self.dark_mode:
            image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(image.rect(), QColor("#ffffff"))
            painter.end()
            pixmap = QPixmap.fromImage(image)
        self.logo_label.setPixmap(
            pixmap.scaled(285, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    @Slot(list)
    def _on_reservations_changed(self, reservations: list[Reservation]) -> None:
        previous = self.reservations
        self.reservations = list(reservations)
        if not self._persist():
            self.reservations = previous
        self.calendar_view.reservations = list(self.reservations)
        self._refresh_workstation_views()

    def _check_reservation_access(self, workstation: Workstation) -> bool:
        try:
            reservations = self.store.read_reservations()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "Reservierungen nicht prüfbar", f"Der gemeinsame Reservierungsstand ist nicht lesbar. Bitte aktualisieren.\n{exc}")
            return False
        apply_reservations([workstation], reservations, self.current_user.upn)
        if workstation.reservation_block_reason:
            QMessageBox.warning(self, "Rechner reserviert", workstation.reservation_block_reason)
            return False
        return True

    def _record_event(
        self,
        workstation: Workstation,
        event_type: EventType,
        result: EventResult,
        reason: str | None = None,
        source: EventSource = EventSource.PORTAL,
    ) -> None:
        """Persist one credential-free event in the shared append-only log."""
        event = SessionEvent(
            event_id=f"EVT-{uuid.uuid4().hex}",
            timestamp_utc=datetime.now(),
            event_type=event_type,
            workstation_id=workstation.workstation_id,
            workstation_hostname=workstation.hostname or workstation.fqdn,
            session_user_upn=workstation.get_rdp_profile(self.current_user.get_rdp_username()).username_hint,
            actor_entra_object_id=self.current_user.object_id,
            actor_upn=self.current_user.upn,
            result=result,
            reason=reason,
            source=source,
        )
        try:
            self.store.append_event(event)
        except OSError as exc:
            logger.warning("Could not write portal event: %s", exc)
            return
        self.session_events.append(event)
        self.session_log_view.add_event(event)
        if self.detail_view.workstation is workstation:
            self.detail_view.set_session_events(
                [item for item in self.session_events if item.workstation_id == workstation.workstation_id]
            )

    @Slot(Workstation)
    def on_connect_requested(self, workstation: Workstation) -> None:
        from portal_app.rdp import focus_rdp_session, has_active_rdp_session, launch_rdp_session

        if not self._check_reservation_access(workstation):
            return

        if has_active_rdp_session(workstation.workstation_id):
            # Raising the window is what the user actually wanted; the old message
            # was correct and useless, because the window is usually just minimised.
            if focus_rdp_session(workstation.workstation_id):
                return
            QMessageBox.warning(
                self,
                "RDP-Fenster bereits aktiv",
                f"Für {workstation.display_name} läuft bereits ein von diesem Portal gestartetes "
                "RDP-Fenster, das sich nicht in den Vordergrund holen ließ. "
                "Wechsle über die Taskleiste dorthin; ein zweiter Start wurde verhindert.",
            )
            return
        owned_sessions = workstation.owned_sessions(self.current_user.windows_accounts())
        if (
            workstation.has_active_session()
            and not workstation.matching_sessions(self.current_user.get_rdp_username())
            and not owned_sessions
        ):
            if not workstation.can_choose_session():
                QMessageBox.warning(self, "Sitzung nicht verfügbar", "Kein eindeutig gemeldetes Sitzungskonto oder die Maschine ist gesperrt.")
                return
            session_accounts = workstation.session_accounts()
            if len(session_accounts) == 1:
                # There is nothing meaningful to choose. Passing the reported
                # account only pre-fills mstsc; Windows still authenticates it.
                account = session_accounts[0]
            else:
                account, accepted = QInputDialog.getItem(self, "Bestehende Sitzung öffnen",
                    "Wähle das Konto der bestehenden Sitzung. Windows fragt dessen Anmeldung ab.\n"
                    "Der angezeigte Windows-Name kann von deiner E-Mail-Adresse abweichen.",
                    session_accounts, 0, False)
                if not accepted:
                    return
            workstation.selected_login_account = account
            self._refresh_login_views(workstation)
        if not workstation.can_connect(
            self.current_user.get_rdp_username(),
            self.current_user.windows_accounts(),
        ):
            QMessageBox.warning(
                self,
                "Verbindung nicht möglich",
                f"{workstation.display_name} ist momentan nicht verfügbar: {workstation.get_status_display()}",
            )
            return
        spelling_warning = workstation.entra_spelling_warning(
            self.current_user.get_rdp_username()
        )
        if spelling_warning:
            question = QMessageBox(self)
            question.setIcon(QMessageBox.Warning)
            question.setWindowTitle("Entra-Anmeldung fehlt")
            question.setText(spelling_warning)
            enable = question.addButton("Entra-Anmeldung aktivieren", QMessageBox.AcceptRole)
            question.addButton("Trotzdem starten", QMessageBox.DestructiveRole)
            question.addButton(QMessageBox.Cancel)
            question.setDefaultButton(enable)
            question.exec()
            clicked = question.clickedButton()
            if clicked is None or question.buttonRole(clicked) == QMessageBox.RejectRole:
                return
            if clicked == enable:
                workstation.entra_sso_enabled = True
                self._commit_workstation(workstation)
                self._persist()
                self._refresh_workstation_views()
        try:
            profile = workstation.get_rdp_profile(self.current_user.get_rdp_username())
            target, _ = profile.resolve_connection_target()
            if profile.entra_sso_enabled and not profile.effective_entra_sso_enabled():
                answer = QMessageBox.question(
                    self,
                    "IP-Verbindung ohne Webkonto",
                    f"{workstation.display_name} wird direkt über {target} verbunden.\n\n"
                    "Windows unterstützt die Webkonto-/Entra-Anmeldung nicht mit einer IP-Adresse. "
                    "Die App deaktiviert sie deshalb für diesen Start; Windows fragt stattdessen "
                    "klassische Anmeldedaten ab.\n\nVerbindung trotzdem starten?",
                    QMessageBox.Yes | QMessageBox.Cancel,
                    QMessageBox.Yes,
                )
                if answer != QMessageBox.Yes:
                    return
            if not profile.trust_unverified_server:
                confirmation = QMessageBox(self)
                confirmation.setIcon(QMessageBox.Warning)
                confirmation.setWindowTitle("Serveridentität bestätigen")
                confirmation.setText(
                    f"Für {workstation.display_name} ({target}) wurde die Serveridentität vom Portal noch nicht geprüft."
                )
                confirmation.setInformativeText(
                    "Windows prüft beim Verbindungsaufbau das Serverzertifikat. "
                    "Eine gespeicherte Ausnahme schaltet diese Prüfung für diese Maschine ab."
                )
                show_warning = confirmation.addButton(
                    "Windows-Warnung anzeigen", QMessageBox.ActionRole
                )
                trust_server = confirmation.addButton(
                    "Vertrauen und künftig überspringen", QMessageBox.AcceptRole
                )
                confirmation.addButton(QMessageBox.Cancel)
                confirmation.setDefaultButton(show_warning)
                confirmation.exec()
                if confirmation.clickedButton() == trust_server:
                    workstation.trust_unverified_server = True
                    self._commit_workstation(workstation)
                    self._persist()
                    self._refresh_workstation_views()
                    profile = workstation.get_rdp_profile(self.current_user.get_rdp_username())
                elif confirmation.clickedButton() != show_warning:
                    return
            if not self._check_reservation_access(workstation):
                return
            success, message = launch_rdp_session(
                profile,
                workstation.workstation_id,
                workstation.display_name,
            )
            if success:
                self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.SUCCESS)
                # Remember which Windows account this person connects as, so the
                # resulting session is recognised as theirs next time instead of
                # showing up as somebody else's and locking them out.
                if self.current_user.claim_account(profile.username_hint):
                    self._saved_user = deepcopy(self.current_user)
                    self._persist()
                    self._refresh_workstation_views()
                self._poll_rdp_sessions()
                QMessageBox.information(
                    self,
                    "Verbindung gestartet",
                    f"Die RDP-Verbindung zu {workstation.display_name} wird über {target} gestartet.",
                )
            else:
                self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.FAILED, message)
                QMessageBox.critical(self, "Verbindung fehlgeschlagen", message)
        except Exception as exc:  # pragma: no cover - platform integration
            logger.exception("Failed to launch RDP")
            self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.FAILED, str(exc))
            QMessageBox.critical(self, "Fehler", f"Die Verbindung konnte nicht gestartet werden: {exc}")

    @Slot(Workstation)
    def _query_live_status(self, workstation: Workstation) -> None:
        current = next(
            (ws for ws in self.workstations if ws.workstation_id == workstation.workstation_id),
            None,
        )
        if current is None:
            return
        self._run_status_update_cycle([current], force=True)

    @Slot(Workstation)
    def _logoff_session(self, workstation: Workstation) -> None:
        from portal_app.ui.widgets.session_logoff_dialog import SessionLogoffDialog

        if workstation.reservation_block_reason:
            QMessageBox.warning(
                self,
                "Fremde Reservierung",
                "Während einer fremden Reservierung wird keine normale Abmeldung angeboten.",
            )
            return
        from portal_app.ui.machine_actions import CONSOLE_LOGOFF_HINT, logoff_candidates

        owned = workstation.owned_sessions(self.current_user.windows_accounts())
        sessions = logoff_candidates(owned)
        if not sessions:
            QMessageBox.warning(self, "Keine passende Sitzung", "Wähle das Konto deiner Sitzung und warte auf eine aktuelle Agent-Meldung mit Anmeldezeitpunkt.")
            return
        sessions = [item for item in sessions if not is_console_session(item)]
        if not sessions:
            # The agent would refuse this, but its reason names a mismatched RDP
            # client. Saying "console session" here is the honest version, and it
            # points at the two ways that do work.
            answer = QMessageBox.question(
                self,
                "Konsolensitzung",
                f"{CONSOLE_LOGOFF_HINT}\n\nMöchtest du stattdessen die administrative "
                "Abmeldung mit Windows-Administratordaten des Zielrechners öffnen?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer == QMessageBox.Yes and (
                self._admin_unlocked or self._request_admin_access()
            ):
                self._admin_logoff_workstation(workstation)
            return
        if len(sessions) > 1:
            labels = [f"Sitzung {item['session_id']} · {item.get('session_state')} · {item['login_time']}" for item in sessions]
            label, accepted = QInputDialog.getItem(self, "Sitzung auswählen", "Welche Sitzung abmelden?", labels, 0, False)
            if not accepted:
                return
            session = sessions[labels.index(label)]
        else:
            session = sessions[0]
        try:
            target, _ = workstation.get_connection_target()
        except ValueError as exc:
            QMessageBox.warning(self, "Ziel fehlt", str(exc))
            return
        dialog = SessionLogoffDialog(
            target,
            workstation.display_name,
            dict(session),
            self,
            expected_agent_id=workstation.agent_workstation_id or workstation.workstation_id,
            status_target=workstation.get_agent_status_target(),
            hostnames=None if workstation.agent_workstation_id else machine_hostnames(workstation),
        )
        dialog.request_finished.connect(
            lambda success, _message, ws=workstation: (
                self._run_status_update_cycle([ws], force=True) if success else None
            )
        )
        dialog.exec()
        dialog.deleteLater()
        self._poll_agent_status()

    @Slot(Workstation)
    def _run_rdp_diagnostics(self, workstation: Workstation) -> None:
        """Show a credential-free RDP preflight report for one workstation."""
        from portal_app.services.rdp_diagnostics import (
            clear_saved_rdp_credentials,
            run_rdp_diagnostics,
        )

        try:
            profile = workstation.get_rdp_profile(self.current_user.get_rdp_username())
            result = run_rdp_diagnostics(profile)
        except Exception as exc:
            logger.exception("RDP diagnostics failed")
            QMessageBox.critical(self, "RDP-Diagnose fehlgeschlagen", str(exc))
            return
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Information if result.port_open else QMessageBox.Warning)
        message.setWindowTitle("RDP-Verbindungsdiagnose")
        message.setText(
            "Der RDP-Port ist erreichbar." if result.port_open else "Der RDP-Port konnte nicht erreicht werden."
        )
        message.setInformativeText(
            f"Der vollstÃ¤ndige, passwortfreie Report wurde gespeichert unter:\n{result.log_path}"
        )
        message.setDetailedText(result.report)
        copy_button = message.addButton("Report kopieren", QMessageBox.ActionRole)
        clear_button = None
        if result.saved_credentials_present:
            clear_button = message.addButton(
                "Gespeicherte Anmeldedaten entfernen", QMessageBox.DestructiveRole
            )
            clear_button.setObjectName("dangerButton")
        message.addButton(QMessageBox.Ok)
        message.exec()
        if message.clickedButton() == copy_button:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(result.report)
        elif message.clickedButton() == clear_button:
            answer = QMessageBox.warning(
                self,
                "Gespeicherte RDP-Anmeldedaten entfernen",
                f"Der gespeicherte Windows-Eintrag für {result.target} wird entfernt.\n\n"
                "Das Kennwort bleibt unbekannt; beim nächsten RDP-Start fragt Windows erneut nach den Anmeldedaten.\n\n"
                "Eintrag wirklich entfernen?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Yes:
                return
            success, detail = clear_saved_rdp_credentials(result.target)
            if success:
                QMessageBox.information(self, "RDP-Anmeldedaten entfernt", detail)
            else:
                QMessageBox.warning(self, "Entfernen fehlgeschlagen", detail)

    def on_refresh(self) -> None:
        try:
            loaded = self.store.load(self.workstations, self.current_user)
        except OSError as exc:
            self._update_storage_status(f"Aktualisierung fehlgeschlagen: {exc}")
            logger.warning("Could not refresh portal storage: %s", exc)
            return
        self.workstations, self.current_user, self.reservations = loaded
        self._apply_local_agent_fallbacks()
        self._pending_save = False
        self._poll_agent_status()
        self.session_events = self.store.load_events()
        self.directory_accounts = self.store.load_directory_accounts()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        self.calendar_view.reservations = list(self.reservations)
        self.session_log_view.set_events(self.session_events)
        self.admin_view.set_storage_directory(str(self.store.directory))
        self._update_storage_status("Gemeinsame Änderungen übernommen")
        self.calendar_view.set_user(self.current_user)
        self.settings_view.set_user(self.current_user)
        self.settings_view.set_theme_mode(self.theme_mode, self.dark_mode)
        self.settings_view.set_status_refresh_interval(
            self.store.status_refresh_interval
        )
        self.agent_poll_timer.setInterval(self.store.status_refresh_interval * 1000)
        self.live_status_poller.set_interval(self.store.status_refresh_interval)
        self.detail_view.set_user(self.current_user)
        self._update_user_header()
        self._apply_theme()
        self._refresh_workstation_views()
        if self.detail_view.workstation is not None:
            selected_id = self.detail_view.workstation.workstation_id
            selected = next((ws for ws in self.workstations if ws.workstation_id == selected_id), None)
            if selected is not None:
                self.detail_view.set_workstation(selected)
            else:
                self._show_machines()

    def _sync_shared_store(self) -> None:
        """Reload an updated OneDrive/SharePoint mirror after another portal saves."""
        if self._pending_save:
            return
        if not self.store.has_external_changes():
            return
        self.on_refresh()

    def _persist(self) -> bool:
        try:
            self.store.save(
                self._saved_workstations,
                self._saved_user,
                self.reservations,
                theme_mode=self.theme_mode,
            )
            self._update_storage_status("Gemeinsamer Stand gespeichert")
            self._pending_save = False
            return True
        except StoreConflictError as exc:
            QMessageBox.warning(
                self,
                "Paralleländerung erkannt",
                f"Die gemeinsame SharePoint-Konfiguration wurde auf einem anderen Portal geändert.\n\n{exc}",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Speichern fehlgeschlagen", f"Die lokalen Testdaten konnten nicht gespeichert werden: {exc}")
        self._update_storage_status("Änderungen NICHT gespeichert – bitte erneut speichern oder aktualisieren")
        self._pending_save = True
        return False

    def _update_storage_status(self, action: str) -> None:
        """Expose the shared storage state without claiming OneDrive server delivery."""
        if not hasattr(self, "admin_view"):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.admin_view.set_storage_status(
            f"{action} · {timestamp} · portal-state.json und portal-events.jsonl"
        )

    def _commit_workstation(self, workstation: Workstation) -> None:
        """Update only the explicitly saved machine in the persistent snapshot."""
        saved = deepcopy(workstation)
        for index, existing in enumerate(self._saved_workstations):
            if existing.workstation_id == workstation.workstation_id:
                self._saved_workstations[index] = saved
                return
        self._saved_workstations.append(saved)

    def _update_summary(self) -> None:
        online = sum(ws.agent_status.value == "online" for ws in self.workstations)
        occupied = sum(ws.has_active_session() for ws in self.workstations)
        self.summary.setText(f"{online} online · {occupied} belegt · {len(self.workstations)} Maschinen")

    def closeEvent(self, event) -> None:  # noqa: N802
        from portal_app.rdp import cleanup_rdp_files, get_active_rdp_sessions

        active = get_active_rdp_sessions()
        if active:
            machine_names = ", ".join(sorted({session.display_name for session in active}))
            answer = QMessageBox.question(
                self,
                "RDP-Verbindung noch aktiv",
                f"Es läuft noch mindestens ein RDP-Fenster für {machine_names}.\n\n"
                "Das Portal beendet diese Verbindung beim Schließen nicht. Auch die entfernte "
                "Windows-Sitzung kann angemeldet bleiben. Portal trotzdem schließen?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        self.rdp_poll_timer.stop()
        self.agent_poll_timer.stop()
        self.live_status_poller.stop()
        self.fallback_scanner.stop()
        cleanup_rdp_files()
        event.accept()

    @staticmethod
    def _application_style(dark_mode: bool = False) -> str:
        light_style = """
            QMainWindow, QWidget#appBackground { background: #eef1f3; color: #17212b; }
            QFrame#appShell { background: #ffffff; border: 1px solid #d9e0e5; border-radius: 14px; }
            QWidget#header { background: #ffffff; border-top-left-radius: 14px; border-top-right-radius: 14px; }
            QLabel#brandLogo { background: transparent; }
            QLabel#productName { color: #526876; border-left: 1px solid #ccd5dc; padding-left: 14px; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }
            QPushButton#userButton { background: transparent; color: #1f3444; border: none; text-align: right; padding: 4px 8px; font-weight: 600; }
            QPushButton#userButton:hover { color: #315e80; background: #eef4f8; border-radius: 7px; }
            QPushButton#avatarButton { background: #e8f0f6; color: #3c6687; border: none; border-radius: 21px; font-weight: 700; }
            QPushButton#avatarButton:hover { background: #d9e8f2; }
            QPushButton#themeButton { background: #ffffff; color: #315e80; border: 1px solid #c8d4dc; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
            QPushButton#themeButton:hover { background: #eef4f8; border-color: #7899af; }
            QWidget#navigation { background: #f8fafb; border-top: 1px solid #e3e8ec; border-bottom: 1px solid #dce3e8; }
            QPushButton#navButton { background: transparent; color: #425c70; border: none; border-bottom: 3px solid transparent; padding: 16px 18px 13px 18px; font-weight: 600; }
            QPushButton#navButton:hover { color: #315e80; background: #eef4f8; }
            QPushButton#navButton:checked { color: #315e80; border-bottom-color: #567f9e; }
            QWidget#content { background: #f7f9fa; }
            QLabel#eyebrow { color: #62839a; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#pageTitle { color: #17232d; }
            QLabel#pageSubtitle { color: #516170; font-size: 9pt; }
            QLabel#summaryBadge { background: #e8f1eb; color: #3d6f4d; border: 1px solid #cfe0d3; border-radius: 14px; padding: 6px 12px; font-weight: 600; font-size: 8pt; }
            QFrame#sessionWarning { background: #fff7e6; border: 1px solid #e4c47d; border-radius: 9px; }
            QLabel#sessionWarningIcon { background: #d89a28; color: #ffffff; border: none; border-radius: 14px; font-size: 12pt; font-weight: 800; }
            QLabel#sessionWarningTitle { color: #684a12; border: none; font-weight: 700; }
            QLabel#sessionWarningText { color: #7a5d26; border: none; font-size: 8pt; }
            QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QTextEdit, QPlainTextEdit {
                background: #ffffff;
                color: #17212b;
                border: 1px solid #b9c7d0;
                border-radius: 7px;
                padding: 7px 10px;
                selection-background-color: #4f7897;
                selection-color: #ffffff;
            }
            QComboBox:hover, QDateEdit:hover, QDateTimeEdit:hover { border-color: #6d91aa; }
            QComboBox::drop-down, QDateEdit::drop-down, QDateTimeEdit::drop-down { border: none; width: 28px; }
            QComboBox QAbstractItemView, QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView {
                background: #ffffff;
                color: #17212b;
                border: 1px solid #9fb2bf;
                selection-background-color: #dceaf3;
                selection-color: #17212b;
            }
            QLineEdit#dashboardSearch, QComboBox#dashboardFilter { background: #ffffff; color: #17212b; border: 1px solid #b9c7d0; border-radius: 8px; padding: 10px 13px; min-height: 20px; }
            QLineEdit#dashboardSearch:focus, QComboBox#dashboardFilter:focus { border-color: #5e87a5; }
            QFrame#pingTool { background: #ffffff; border: 1px solid #d5dde3; border-radius: 9px; }
            QLabel#pingTitle { color: #334d60; font-weight: 700; }
            QLineEdit#pingInput { background: #f8fafb; color: #283641; border: 1px solid #ccd6dd; border-radius: 6px; padding: 7px 10px; }
            QLineEdit#pingInput:focus { background: #ffffff; border-color: #5e87a5; }
            QLabel#pingResult { color: #73828d; font-size: 8pt; }
            QLabel#pingResult[pingOk="true"] { color: #39704a; font-weight: 700; }
            QLabel#pingResult[pingOk="false"] { color: #9b4144; font-weight: 700; }
            QPushButton#toolbarButton { background: #ffffff; color: #385d77; border: 1px solid #c8d4dc; border-radius: 8px; padding: 9px 14px; font-weight: 600; }
            QPushButton#toolbarButton:hover { background: #eef4f8; border-color: #7899af; }
            QPushButton#cardPrimaryButton { background: #4f7897; color: #ffffff; border: 1px solid #4f7897; border-radius: 7px; padding: 9px 14px; font-weight: 600; }
            QPushButton#cardPrimaryButton:hover { background: #416985; }
            QPushButton#cardPrimaryButton:disabled { background: #e8ecef; color: #87939c; border-color: #d8dfe4; }
            QPushButton#dangerButton { background: #fff4f3; color: #953f43; border: 1px solid #e0b6b8; border-radius: 7px; padding: 8px 12px; }
            QScrollArea#machineScroll, QWidget#gridHost, QScrollArea#detailScroll, QWidget#detailContent { background: transparent; }
            QScrollArea#settingsScroll, QWidget#settingsContent { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 0; }
            QScrollBar::handle:vertical { background: #9db0bd; border-radius: 5px; min-height: 36px; }
            QScrollBar::handle:vertical:hover { background: #6f8b9e; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QFrame#workstationCard { background: #ffffff; border: 1px solid #d5dde3; border-radius: 11px; }
            QFrame#workstationCard:hover { border: 1px solid #7799b0; background: #fbfdfe; }
            QLabel#cardTitle { color: #1d2b36; }
            QLabel#cardStatus { color: #344652; font-size: 9pt; font-weight: 600; }
            QLabel#cardMeta { color: #526572; font-size: 8pt; }
            QPushButton#cardSecondaryButton { background: #ffffff; color: #526673; border: 1px solid #d3dbe1; border-radius: 7px; padding: 8px 12px; }
            QPushButton#cardSecondaryButton:hover { background: #f1f5f7; }
            QFrame#addWorkstationCard { background: #f8fafb; border: 2px dashed #b8c6cf; border-radius: 11px; }
            QFrame#addWorkstationCard:hover { background: #f0f5f8; border-color: #6f91a9; }
            QLabel#addCardPlus { color: #557d99; font-size: 42px; font-weight: 300; }
            QLabel#addCardTitle { color: #334d60; font-size: 10pt; font-weight: 600; }
            QFrame#detailCard { background: #ffffff; border: 1px solid #d8e0e5; border-radius: 10px; }
            QPlainTextEdit#networkOutput { background: #18232c; color: #dce7ee; border: 1px solid #31434f; border-radius: 7px; padding: 10px; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 8pt; selection-background-color: #4f7897; }
            QLabel#detailCardTitle { color: #263844; font-size: 11pt; font-weight: 700; }
            QLabel#detailLabel { color: #536774; font-size: 8pt; }
            QLabel#detailValue { color: #263844; font-weight: 600; }
            QLabel#detailMuted { color: #536774; font-size: 8pt; }
            QLabel#detailMuted[pingOk="true"] { color: #39704a; font-weight: 700; }
            QLabel#detailMuted[pingOk="false"] { color: #9b4144; font-weight: 700; }
            QFrame#detailDivider { color: #e2e7ea; }
            QLabel#dialogTitle { color: #20323f; font-size: 13pt; font-weight: 700; }
            QLabel#dialogNote { color: #536774; font-size: 8pt; }
            QLabel#dialogFormLabel { color: #263844; font-weight: 600; }
            QLabel#dialogWarning { color: #825b1a; font-weight: 600; }
            QLabel#calendarRange { color: #38566c; font-weight: 600; }
            QLabel#adminAccessStatus { background: #eef1f3; color: #6f7d87; border-radius: 11px; padding: 5px 9px; font-size: 8pt; font-weight: 600; }
            QLabel#adminAccessStatus[unlocked="true"] { background: #e4f0e7; color: #39704a; }
            QLabel#logTitle { color: #20323f; font-size: 13pt; font-weight: 700; }
            QFrame#filterBar { background: #eef3f6; border: 1px solid #cad6de; border-radius: 8px; }
            QTableWidget#calendarTable { gridline-color: #ffffff; }
            QTableWidget#calendarTable::item { padding: 6px; }
            QTableView, QTableWidget { background: #ffffff; color: #17212b; alternate-background-color: #f8fafb; border: 1px solid #d6dfe5; border-radius: 8px; gridline-color: #e6ebee; selection-background-color: #dceaf3; selection-color: #1e3545; }
            QTableCornerButton::section { background: #e8eff3; border: 1px solid #cbd7df; }
            QHeaderView::section { background: #e8eff3; color: #365466; border: none; border-bottom: 1px solid #cbd7df; padding: 9px 10px; font-weight: 600; }
            QDialog { background: #f7f9fa; }
            QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QDialog QGroupBox {
                color: #263844;
            }
            QMessageBox { background: #f7f9fa; color: #17212b; }
            QMessageBox QLabel { color: #17212b; }
            QMessageBox QPushButton, QDialogButtonBox QPushButton {
                background: #ffffff;
                color: #263f52;
                border: 1px solid #aebfca;
                border-radius: 7px;
                font-size: 9pt;
                min-height: 22px;
                padding: 7px 16px;
                min-width: 82px;
                font-weight: 600;
            }
            QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover { background: #edf4f8; border-color: #6389a4; }
            QMessageBox QPushButton:default, QDialogButtonBox QPushButton:default { background: #4f7897; color: #ffffff; border-color: #4f7897; }
            QMessageBox QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover { background: #416985; border-color: #416985; }
            QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit, QDialog QDateTimeEdit,
            QDialog QSpinBox, QDialog QTextEdit, QDialog QPlainTextEdit {
                background: #ffffff;
                color: #17212b;
                font-size: 9pt;
                min-height: 22px;
                placeholder-text-color: #7a8994;
                border: 1px solid #cbd6dd;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #eef2f4;
                color: #5e6d77;
            }
            QDialog QTabWidget::pane { background: #ffffff; border: 1px solid #d4dde3; border-radius: 7px; }
            QDialog QTabBar::tab { background: #eaf0f3; padding: 9px 16px; border: 1px solid #d4dde3; }
            QDialog QTabBar::tab:selected { background: #ffffff; color: #315e80; }
            QWizard#machineRegistrationWizard, QWizard#machineRegistrationWizard > QWidget,
            QWizard#machineRegistrationWizard QFrame, QWizardPage#machineWizardPage { background: #f7f9fa; color: #263844; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #263844; }
            QWizard QLineEdit { background: #ffffff; color: #17212b; font-size: 9pt; min-height: 22px; placeholder-text-color: #7a8994; border: 1px solid #aebfca; border-radius: 6px; padding: 6px 10px; }
            QWizard QPushButton { background: #ffffff; color: #263f52; font-size: 9pt; min-height: 22px; border: 1px solid #aebfca; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
            QWizard QPushButton:hover { background: #edf4f8; border-color: #6389a4; }
            QWizard QPushButton:default { background: #4f7897; color: #ffffff; border-color: #4f7897; }
            QWizard QPushButton:disabled { background: #edf1f3; color: #8a99a3; border-color: #d3dce1; }
        """
        if not dark_mode:
            return light_style
        return light_style + """
            QMainWindow, QWidget#appBackground { background: #101820; color: #edf3f8; }
            QWidget#content { background: #15212b; }
            QFrame#appShell, QWidget#header { background: #192833; border-color: #36505f; }
            QWidget#navigation { background: #1d2d38; border-color: #3b5565; }
            QLabel#productName { color: #a9c2d2; border-left-color: #486172; }
            QPushButton#themeButton { background: #263c4c; color: #f4f8fb; border: 1px solid #537386; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
            QPushButton#themeButton:hover { background: #304b5e; border-color: #83abc2; }
            QPushButton#userButton { color: #f4f8fb; }
            QPushButton#userButton:hover { color: #ffffff; background: #293e4e; }
            QPushButton#avatarButton { background: #29495f; color: #e8f4fb; }
            QPushButton#avatarButton:hover { background: #35617d; }
            QPushButton#navButton { color: #c4d5e0; }
            QPushButton#navButton:hover { color: #ffffff; background: #293e4e; }
            QPushButton#navButton:checked { color: #ffffff; border-bottom-color: #79abc9; }
            QLabel#eyebrow { color: #9fc5db; }
            QLabel#pageTitle { color: #f4f8fb; }
            QLabel#pageSubtitle { color: #b8c8d3; }
            QLabel#summaryBadge { background: #1d473c; color: #c4f0d1; border-color: #3c7861; }
            QFrame#sessionWarning { background: #413516; border-color: #a98438; }
            QLabel#sessionWarningTitle { color: #ffdf9b; }
            QLabel#sessionWarningText { color: #f4d59a; }
            QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QSpinBox, QPlainTextEdit, QTextEdit { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; selection-background-color: #4f7897; selection-color: #ffffff; }
            QLineEdit#dashboardSearch, QComboBox#dashboardFilter, QLineEdit#pingInput { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; }
            QLineEdit#dashboardSearch:focus, QLineEdit#pingInput:focus { background: #1a2a35; color: #f1f6fa; border-color: #8fc1dd; }
            QComboBox QAbstractItemView, QDateEdit QAbstractItemView, QDateTimeEdit QAbstractItemView { background: #1c2d38; color: #f1f6fa; border-color: #59788b; selection-background-color: #3a6884; selection-color: #ffffff; }
            QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QDateTimeEdit:focus, QTextEdit:focus { border-color: #8fc1dd; }
            QFrame#pingTool, QFrame#workstationCard, QFrame#detailCard { background: #1c2d38; border-color: #3d5868; }
            QFrame#workstationCard:hover { background: #213642; border-color: #79a6bf; }
            QLabel#pingTitle, QLabel#cardTitle, QLabel#cardStatus, QLabel#detailCardTitle, QLabel#detailValue, QLabel#dialogTitle { color: #f3f7fa; }
            QLabel#logTitle, QLabel#dialogFormLabel { color: #f3f7fa; }
            QLabel#pingResult, QLabel#cardMeta, QLabel#detailLabel, QLabel#detailMuted, QLabel#dialogNote, QLabel#calendarRange { color: #b9cad5; }
            QLabel#dialogWarning { color: #ffda89; font-weight: 600; }
            QLabel#adminAccessStatus { background: #2b3b46; color: #d3dee5; }
            QLabel#adminAccessStatus[unlocked="true"] { background: #1c4b3a; color: #c4f0d1; }
            QPushButton#toolbarButton, QPushButton#cardSecondaryButton { background: #223743; color: #eaf3f8; border-color: #527082; }
            QPushButton#toolbarButton:hover, QPushButton#cardSecondaryButton:hover { background: #2d4758; border-color: #86b0c8; }
            QPushButton#cardPrimaryButton { background: #477896; border-color: #477896; color: #ffffff; }
            QPushButton#cardPrimaryButton:hover { background: #5c91b1; border-color: #5c91b1; }
            QPushButton#dangerButton { background: #482a30; color: #ffd7d9; border-color: #9d6268; }
            QPushButton#dangerButton:hover { background: #60343b; border-color: #d1878c; }
            QFrame#addWorkstationCard { background: #1a2a35; border-color: #5b788a; }
            QFrame#addWorkstationCard:hover { background: #213743; border-color: #8eb8cf; }
            QLabel#addCardPlus, QLabel#addCardTitle { color: #d9ebf5; }
            QTableView, QTableWidget { background: #1a2a35; color: #f0f5f8; alternate-background-color: #203440; border-color: #456172; gridline-color: #35505f; selection-background-color: #3a6884; selection-color: #ffffff; }
            QTableCornerButton::section { background: #263b48; border: 1px solid #456172; }
            QDialog QListWidget { background: #1a2a35; color: #f0f5f8; border: 1px solid #456172; border-radius: 7px; selection-background-color: #3a6884; selection-color: #ffffff; }
            QDialog QListWidget::item { padding: 6px 9px; }
            QDialog QListWidget::item:hover { background: #263f4e; }
            QScrollBar::handle:vertical { background: #557386; }
            QScrollBar::handle:vertical:hover { background: #83abc2; }
            QFrame#filterBar { background: #1c2d38; border: 1px solid #3d5868; border-radius: 8px; }
            QHeaderView::section { background: #263b48; color: #edf4f8; border-bottom-color: #456172; }
            QTableWidget#calendarTable::item { color: #eef4f8; }
            QDialog, QMessageBox { background: #192833; color: #edf3f8; }
            QDialog QLabel, QDialog QCheckBox, QDialog QRadioButton, QDialog QGroupBox {
                color: #e7f0f5;
            }
            QMessageBox QLabel { color: #edf3f8; }
            QMessageBox QPushButton, QDialogButtonBox QPushButton { background: #263d4b; color: #f3f8fb; font-size: 9pt; min-height: 22px; border-color: #628196; }
            QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QMessageBox QPushButton:default, QDialogButtonBox QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QMessageBox QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover { background: #6ca6c7; border-color: #b5d9ea; }
            QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit, QDialog QDateTimeEdit,
            QDialog QSpinBox, QDialog QTextEdit, QDialog QPlainTextEdit {
                background: #1a2a35;
                color: #f1f6fa;
                font-size: 9pt;
                min-height: 22px;
                placeholder-text-color: #8fa6b5;
                border-color: #557386;
                selection-background-color: #4f7897;
                selection-color: #ffffff;
                padding: 6px 10px;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #22343f;
                color: #aebfca;
                border-color: #456172;
            }
            QDialog QTabWidget::pane { background: #1a2a35; border-color: #456172; }
            QDialog QTabBar::tab { background: #263b48; color: #c8d8e2; border-color: #456172; }
            QDialog QTabBar::tab:selected { background: #1a2a35; color: #ffffff; }
            QWizard#machineRegistrationWizard, QWizard#machineRegistrationWizard > QWidget,
            QWizard#machineRegistrationWizard QFrame, QWizardPage#machineWizardPage { background: #192833; color: #e7f0f5; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #e7f0f5; }
            QWizard QLineEdit { background: #1a2a35; color: #f1f6fa; font-size: 9pt; min-height: 22px; placeholder-text-color: #8fa6b5; border: 1px solid #557386; border-radius: 6px; padding: 6px 10px; }
            QWizard QLineEdit:disabled { background: #22343f; color: #aebfca; border-color: #456172; }
            QWizard QPushButton { background: #263d4b; color: #f3f8fb; font-size: 9pt; min-height: 22px; border: 1px solid #628196; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
            QWizard QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QWizard QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QWizard QPushButton:disabled { background: #22343f; color: #8095a3; border-color: #3d5868; }
            QCheckBox { color: #e7f0f5; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #789bae; background: #1a2a35; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #5f96b8; border-color: #8fc1dd; }
            QToolTip { background: #101820; color: #f3f7fa; border: 1px solid #5b788a; }
        """


__all__ = ["MainWindow"]
