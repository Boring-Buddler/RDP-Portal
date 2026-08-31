"""Main window for the locally testable Kirschke RDP portal."""

from __future__ import annotations

import logging
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from secrets import compare_digest

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
from portal_app.models.workstation import Workstation, create_initial_workstations
from portal_app.services.local_store import LocalStore
from portal_app.services.local_identity import detect_initial_user
from portal_app.services.agent_status import LocalAgentStatusService
from portal_app.ui.design import Typography
from portal_app.ui.icons import kirschke_window_icon
from portal_app.ui.widgets.management_pages import AdministrationWidget, SettingsWidget
from portal_app.ui.widgets.reservation_calendar import ReservationCalendarWidget
from portal_app.ui.widgets.session_log import SessionLogWidget
from portal_app.ui.widgets.user_settings_dialog import UserSettingsDialog
from portal_app.ui.widgets.workstation_cards import WorkstationCardsWidget
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.workstation_dialog import WorkstationDialog
from portal_app.ui.widgets.machine_registration_wizard import MachineRegistrationWizard
from shared.enums import EventResult, EventSource, EventType

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
    ADMIN_PASSWORD = "Kirschke"  # noqa: S105 - explicitly requested for the local test build

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kirschke · RDP Portal")
        self.logo_path = Path(__file__).resolve().parent / "assets" / "kirschke_logo.png"
        self.setWindowIcon(kirschke_window_icon())
        self.setMinimumSize(QSize(1080, 720))
        self.resize(1360, 860)

        self.store = LocalStore()
        self.agent_status_service = LocalAgentStatusService()
        self.workstations: list[Workstation] = []
        self.reservations: list[Reservation] = []
        self.session_events: list[SessionEvent] = []
        self.current_user = detect_initial_user(MockUser.create_user())
        self.nav_buttons: list[QPushButton] = []
        self._admin_unlocked = False
        self._current_rdp_notice_key: str | None = None
        self._dismissed_rdp_notice_key: str | None = None
        self._load_data()
        self._create_ui()
        self._connect_signals()
        self._apply_theme()
        self.rdp_poll_timer = QTimer(self)
        self.rdp_poll_timer.setInterval(1500)
        self.rdp_poll_timer.timeout.connect(self._poll_rdp_sessions)
        self.rdp_poll_timer.start()
        self._poll_rdp_sessions()
        self.agent_poll_timer = QTimer(self)
        self.agent_poll_timer.setInterval(5000)
        self.agent_poll_timer.timeout.connect(self._poll_agent_status)
        self.agent_poll_timer.start()
        self._poll_agent_status()
        self.shared_store_sync_timer = QTimer(self)
        self.shared_store_sync_timer.setInterval(5000)
        self.shared_store_sync_timer.timeout.connect(self._sync_shared_store)
        self.shared_store_sync_timer.start()

    def _load_data(self) -> None:
        fallback = create_initial_workstations()
        self.workstations, self.current_user, self.reservations = self.store.load(fallback, self.current_user)
        self.session_events = self.store.load_events()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        try:
            self.store.save(self._saved_workstations, self._saved_user, self.reservations, self.store.theme_mode)
            self.store.initialize_event_log()
        except OSError as exc:
            logger.warning("Could not initialize shared portal storage: %s", exc)

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
        product = QLabel("RDP PORTAL · TEST")
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
        self.page_title.setFont(Typography.get_font(28, Typography.FONT_WEIGHT_BOLD))
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

        self.rdp_warning_banner = QFrame()
        self.rdp_warning_banner.setObjectName("rdpWarningBanner")
        warning_layout = QHBoxLayout(self.rdp_warning_banner)
        warning_layout.setContentsMargins(16, 11, 10, 11)
        warning_layout.setSpacing(12)
        warning_icon = QLabel("!")
        warning_icon.setObjectName("rdpWarningIcon")
        warning_icon.setFixedSize(28, 28)
        warning_icon.setAlignment(Qt.AlignCenter)
        warning_layout.addWidget(warning_icon)
        warning_copy = QVBoxLayout()
        warning_copy.setSpacing(1)
        self.rdp_warning_title = QLabel("RDP-Sitzung aktiv")
        self.rdp_warning_title.setObjectName("rdpWarningTitle")
        warning_copy.addWidget(self.rdp_warning_title)
        self.rdp_warning_text = QLabel()
        self.rdp_warning_text.setObjectName("rdpWarningText")
        self.rdp_warning_text.setWordWrap(True)
        warning_copy.addWidget(self.rdp_warning_text)
        warning_layout.addLayout(warning_copy, 1)
        dismiss = QPushButton("Ausblenden")
        dismiss.setObjectName("warningDismissButton")
        dismiss.clicked.connect(self._dismiss_rdp_warning)
        warning_layout.addWidget(dismiss)
        self.rdp_warning_banner.setVisible(False)
        layout.addWidget(self.rdp_warning_banner)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")
        self.overview_view = WorkstationCardsWidget(self.workstations, self.current_user, self)
        self.stack.addWidget(self.overview_view)
        self.calendar_view = ReservationCalendarWidget(
            self.workstations, self.reservations, self.current_user, self
        )
        self.stack.addWidget(self.calendar_view)
        self.session_log_view = SessionLogWidget([], self.current_user, self)
        self.session_log_view.set_events(self.session_events)
        self.stack.addWidget(self.session_log_view)
        self.admin_view = AdministrationWidget(self.workstations, self)
        self.admin_view.set_storage_directory(str(self.store.directory))
        self.stack.addWidget(self.admin_view)
        self.settings_view = SettingsWidget(
            self.current_user,
            theme_mode=self.theme_mode,
            dark_mode=self.dark_mode,
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
        self.overview_view.add_requested.connect(self._add_workstation)
        self.overview_view.refresh_requested.connect(self.on_refresh)
        self.admin_view.add_requested.connect(self._add_workstation)
        self.admin_view.edit_requested.connect(self._edit_workstation)
        self.admin_view.force_disconnect_requested.connect(self._force_disconnect_workstation)
        self.admin_view.delete_requested.connect(self._delete_workstation)
        self.admin_view.lock_requested.connect(self._lock_admin)
        self.admin_view.storage_directory_requested.connect(self._change_storage_directory)
        self.settings_view.edit_user_requested.connect(self._edit_user)
        self.settings_view.agent_refresh_requested.connect(self._poll_agent_status)
        self.settings_view.theme_changed.connect(self._set_theme_mode)
        self.calendar_view.reservations_changed.connect(self._on_reservations_changed)
        self.detail_view.back_requested.connect(self._show_machines)
        self.detail_view.edit_requested.connect(self._edit_workstation)
        self.detail_view.connect_requested.connect(self.on_connect_requested)
        self.detail_view.diagnostics_requested.connect(self._run_rdp_diagnostics)
        self.detail_view.workstation_updated.connect(self._on_workstation_updated)
        self.workstation_selected.connect(self.detail_view.set_workstation)

    @Slot()
    def _dismiss_rdp_warning(self) -> None:
        self._dismissed_rdp_notice_key = self._current_rdp_notice_key
        self.rdp_warning_banner.setVisible(False)

    @Slot()
    def _poll_rdp_sessions(self) -> None:
        """Monitor RDP clients launched by this portal without blocking the UI."""
        from portal_app.rdp import consume_finished_rdp_sessions, get_active_rdp_sessions

        active = get_active_rdp_sessions()
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
        if active:
            notice_key = "active:" + ",".join(str(session.pid) for session in sorted(active, key=lambda item: item.pid))
            self._current_rdp_notice_key = notice_key
            machine_names = ", ".join(sorted({session.display_name for session in active}))
            count = len(active)
            self.rdp_warning_title.setText(
                f"{count} lokales RDP-Fenster aktiv"
                if count == 1
                else f"{count} lokale RDP-Fenster aktiv"
            )
            self.rdp_warning_text.setText(
                f"{machine_names} · Beim Trennen kann die Windows-Sitzung angemeldet bleiben und den Zugang belegen."
            )
            if self._dismissed_rdp_notice_key != notice_key:
                self.rdp_warning_banner.setVisible(True)
        elif finished:
            notice_key = "finished:" + ",".join(str(session.pid) for session in sorted(finished, key=lambda item: item.pid))
            self._current_rdp_notice_key = notice_key
            machine_names = ", ".join(sorted({session.display_name for session in finished}))
            self.rdp_warning_title.setText("RDP-Fenster wurde geschlossen")
            self.rdp_warning_text.setText(
                f"{machine_names} · Das beendet nicht zwingend die Windows-Sitzung. Bitte auf der Maschine abmelden."
            )
            if self._dismissed_rdp_notice_key != notice_key:
                self.rdp_warning_banner.setVisible(True)
        else:
            self._current_rdp_notice_key = None
            self._dismissed_rdp_notice_key = None

    @Slot()
    def _poll_agent_status(self) -> None:
        """Merge locally published WTS status into matching test workstations."""
        changed = self.agent_status_service.apply(self.workstations)
        self.settings_view.set_agent_bridge_status(
            self.agent_status_service.last_match_count,
            self.agent_status_service.last_snapshot_count,
            str(self.agent_status_service.directory),
        )
        if not changed:
            return
        self._saved_workstations = deepcopy(self.workstations)
        self._persist()
        self._refresh_workstation_views()
        if self.detail_view.workstation is not None:
            self.detail_view.set_workstation(self.detail_view.workstation)

    def _on_navigation_clicked(self, button: QPushButton) -> None:
        page_index = int(button.property("pageIndex"))
        if page_index == self.PAGE_ADMIN and not self._admin_unlocked:
            if not self._request_admin_access():
                current_page = self.stack.currentIndex()
                fallback_page = current_page if 0 <= current_page < self.PAGE_DETAIL else self.PAGE_MACHINES
                self.nav_buttons[fallback_page].setChecked(True)
                return
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

    def _request_admin_access(self) -> bool:
        password, accepted = QInputDialog.getText(
            self,
            "Admin-Zugang",
            "Passwort für den Administrationsbereich:",
            QLineEdit.Password,
        )
        if not accepted:
            return False
        if not self._is_admin_password_valid(password):
            QMessageBox.warning(self, "Zugriff verweigert", "Das eingegebene Admin-Passwort ist nicht korrekt.")
            return False
        self._admin_unlocked = True
        self.admin_view.set_access_status(True)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin · offen")
        return True

    @classmethod
    def _is_admin_password_valid(cls, password: str) -> bool:
        return compare_digest(password, cls.ADMIN_PASSWORD)

    def _lock_admin(self) -> None:
        self._admin_unlocked = False
        self.admin_view.set_access_status(False)
        self.nav_buttons[self.PAGE_ADMIN].setText("Admin")
        self._show_machines()

    @Slot(str)
    def _change_storage_directory(self, directory: str) -> None:
        try:
            self.store.relocate(Path(directory), move_files=True)
            self.admin_view.set_storage_directory(str(self.store.directory))
            self._persist()
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
        self._refresh_workstation_views()
        self.detail_view.set_workstation(workstation)
        self._commit_workstation(workstation)
        self._persist()

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
        self.calendar_view.reservations = self.reservations
        self._refresh_workstation_views()
        if (
            self.detail_view.workstation is not None
            and self.detail_view.workstation.workstation_id == workstation.workstation_id
        ):
            self._show_machines()
        self._persist()

    def _refresh_workstation_views(self) -> None:
        self.overview_view.set_workstations(self.workstations)
        self.calendar_view.set_workstations(self.workstations)
        self.admin_view.set_workstations(self.workstations)
        self._update_summary()

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
        self.reservations = reservations
        self._persist()

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
            session_user_upn=self.current_user.get_rdp_username(),
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
        from portal_app.rdp import has_active_rdp_session, launch_rdp_session

        if has_active_rdp_session(workstation.workstation_id):
            QMessageBox.warning(
                self,
                "RDP-Fenster bereits aktiv",
                f"Für {workstation.display_name} läuft bereits ein von diesem Portal gestartetes RDP-Fenster. "
                "Ein zweiter Start wurde verhindert.",
            )
            return
        if workstation.has_active_session():
            QMessageBox.warning(
                self,
                "Zugang durch Sitzung belegt",
                f"{workstation.display_name} ist durch eine Windows-Sitzung belegt "
                f"({workstation.get_status_display()}, {workstation.get_session_user_display()}).\n\n"
                "Auch eine getrennte Sitzung kann angemeldet bleiben und den Zugang blockieren. "
                "Bitte zuerst vollständig abmelden.",
            )
            return
        if not workstation.can_connect():
            QMessageBox.warning(
                self,
                "Verbindung nicht möglich",
                f"{workstation.display_name} ist momentan nicht verfügbar: {workstation.get_status_display()}",
            )
            return
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
                confirmation.setWindowTitle("ServeridentitÃ¤t bestÃ¤tigen")
                confirmation.setText(
                    f"Windows kann die IdentitÃ¤t von {workstation.display_name} ({target}) nicht bestÃ¤tigen."
                )
                confirmation.setInformativeText(
                    "PrÃ¼fen Sie vor dem Fortfahren, ob diese Zieladresse zur gewÃ¼nschten Maschine gehÃ¶rt. "
                    "Sie kÃ¶nnen die Windows-Warnung einmalig anzeigen lassen oder diese Maschine bewusst "
                    "als Ausnahme speichern. Bei einer Ausnahme prÃ¼ft Windows die ServeridentitÃ¤t nicht mehr."
                )
                show_warning = confirmation.addButton(
                    "Windows-Warnung anzeigen", QMessageBox.ActionRole
                )
                trust_server = confirmation.addButton(
                    "Vertrauen und kÃ¼nftig Ã¼berspringen", QMessageBox.AcceptRole
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
            success, message = launch_rdp_session(
                profile,
                workstation.workstation_id,
                workstation.display_name,
            )
            if success:
                self._record_event(workstation, EventType.LAUNCH_REQUESTED, EventResult.SUCCESS)
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
    def _run_rdp_diagnostics(self, workstation: Workstation) -> None:
        """Show a credential-free RDP preflight report for one workstation."""
        from portal_app.services.rdp_diagnostics import run_rdp_diagnostics

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
        message.addButton(QMessageBox.Ok)
        message.exec()
        if message.clickedButton() == copy_button:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(result.report)

    def on_refresh(self) -> None:
        self.workstations, self.current_user, self.reservations = self.store.load(
            self.workstations, self.current_user
        )
        self.session_events = self.store.load_events()
        self.theme_mode = self.store.theme_mode
        self.dark_mode = self._resolve_dark_mode()
        self._saved_workstations = deepcopy(self.workstations)
        self._saved_user = deepcopy(self.current_user)
        self.calendar_view.reservations = self.reservations
        self.session_log_view.set_events(self.session_events)
        self.admin_view.set_storage_directory(str(self.store.directory))
        self.calendar_view.set_user(self.current_user)
        self.settings_view.set_user(self.current_user)
        self.settings_view.set_theme_mode(self.theme_mode, self.dark_mode)
        self.detail_view.set_user(self.current_user)
        self._update_user_header()
        self._apply_theme()
        self._refresh_workstation_views()

    def _sync_shared_store(self) -> None:
        """Reload an updated OneDrive/SharePoint mirror after another portal saves."""
        if not self.store.has_external_changes():
            return
        self.on_refresh()

    def _persist(self) -> None:
        try:
            self.store.save(
                self._saved_workstations,
                self._saved_user,
                self.reservations,
                theme_mode=self.theme_mode,
            )
        except OSError as exc:
            QMessageBox.warning(self, "Speichern fehlgeschlagen", f"Die lokalen Testdaten konnten nicht gespeichert werden: {exc}")

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
        cleanup_rdp_files()
        event.accept()

    @staticmethod
    def _application_style(dark_mode: bool = False) -> str:
        light_style = """
            QMainWindow, QWidget#appBackground { background: #eef1f3; color: #17212b; font-family: "Segoe UI"; font-size: 14px; }
            QFrame#appShell { background: #ffffff; border: 1px solid #d9e0e5; border-radius: 14px; }
            QWidget#header { background: #ffffff; border-top-left-radius: 14px; border-top-right-radius: 14px; }
            QLabel#brandLogo { background: transparent; }
            QLabel#productName { color: #526876; border-left: 1px solid #ccd5dc; padding-left: 14px; font-size: 12px; font-weight: 600; letter-spacing: 1px; }
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
            QLabel#eyebrow { color: #62839a; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
            QLabel#pageTitle { color: #17232d; }
            QLabel#pageSubtitle { color: #516170; font-size: 14px; }
            QLabel#summaryBadge { background: #e8f1eb; color: #3d6f4d; border: 1px solid #cfe0d3; border-radius: 14px; padding: 6px 12px; font-weight: 600; font-size: 12px; }
            QFrame#rdpWarningBanner, QFrame#sessionWarning { background: #fff7e6; border: 1px solid #e4c47d; border-radius: 9px; }
            QLabel#rdpWarningIcon, QLabel#sessionWarningIcon { background: #d89a28; color: #ffffff; border: none; border-radius: 14px; font-size: 17px; font-weight: 800; }
            QLabel#rdpWarningTitle, QLabel#sessionWarningTitle { color: #684a12; border: none; font-weight: 700; }
            QLabel#rdpWarningText, QLabel#sessionWarningText { color: #7a5d26; border: none; font-size: 12px; }
            QPushButton#warningDismissButton { background: transparent; color: #70531d; border: 1px solid #d7b66d; border-radius: 6px; padding: 6px 10px; }
            QPushButton#warningDismissButton:hover { background: #ffefc9; }
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
            QLabel#pingResult { color: #73828d; font-size: 12px; }
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
            QLabel#cardStatus { color: #344652; font-size: 13px; font-weight: 600; }
            QLabel#cardMeta { color: #526572; font-size: 12px; }
            QPushButton#cardSecondaryButton { background: #ffffff; color: #526673; border: 1px solid #d3dbe1; border-radius: 7px; padding: 8px 12px; }
            QPushButton#cardSecondaryButton:hover { background: #f1f5f7; }
            QFrame#addWorkstationCard { background: #f8fafb; border: 2px dashed #b8c6cf; border-radius: 11px; }
            QFrame#addWorkstationCard:hover { background: #f0f5f8; border-color: #6f91a9; }
            QLabel#addCardPlus { color: #557d99; font-size: 42px; font-weight: 300; }
            QLabel#addCardTitle { color: #334d60; font-size: 15px; font-weight: 600; }
            QFrame#detailCard { background: #ffffff; border: 1px solid #d8e0e5; border-radius: 10px; }
            QPlainTextEdit#networkOutput { background: #18232c; color: #dce7ee; border: 1px solid #31434f; border-radius: 7px; padding: 10px; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; selection-background-color: #4f7897; }
            QLabel#detailCardTitle { color: #263844; font-size: 16px; font-weight: 700; }
            QLabel#detailLabel { color: #536774; font-size: 12px; }
            QLabel#detailValue { color: #263844; font-weight: 600; }
            QLabel#detailMuted { color: #536774; font-size: 12px; }
            QLabel#detailMuted[pingOk="true"] { color: #39704a; font-weight: 700; }
            QLabel#detailMuted[pingOk="false"] { color: #9b4144; font-weight: 700; }
            QFrame#detailDivider { color: #e2e7ea; }
            QLabel#dialogTitle { color: #20323f; font-size: 20px; font-weight: 700; }
            QLabel#dialogNote { color: #536774; font-size: 12px; }
            QLabel#dialogFormLabel { color: #263844; font-weight: 600; }
            QLabel#dialogWarning { color: #825b1a; font-weight: 600; }
            QLabel#calendarRange { color: #38566c; font-weight: 600; }
            QLabel#adminAccessStatus { background: #eef1f3; color: #6f7d87; border-radius: 11px; padding: 5px 9px; font-size: 11px; font-weight: 600; }
            QLabel#adminAccessStatus[unlocked="true"] { background: #e4f0e7; color: #39704a; }
            QLabel#logTitle { color: #20323f; font-size: 20px; font-weight: 700; }
            QFrame#filterBar { background: #eef3f6; border: 1px solid #cad6de; border-radius: 8px; }
            QTableWidget#calendarTable { gridline-color: #ffffff; }
            QTableWidget#calendarTable::item { padding: 6px; }
            QTableView, QTableWidget { background: #ffffff; alternate-background-color: #f8fafb; border: 1px solid #d6dfe5; border-radius: 8px; gridline-color: #e6ebee; selection-background-color: #dceaf3; selection-color: #1e3545; }
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
                placeholder-text-color: #7a8994;
                border: 1px solid #cbd6dd;
                border-radius: 6px;
                padding: 7px 9px;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #eef2f4;
                color: #5e6d77;
            }
            QDialog QTabWidget::pane { background: #ffffff; border: 1px solid #d4dde3; border-radius: 7px; }
            QDialog QTabBar::tab { background: #eaf0f3; padding: 9px 16px; border: 1px solid #d4dde3; }
            QDialog QTabBar::tab:selected { background: #ffffff; color: #315e80; }
            QWizard, QWizardPage { background: #f7f9fa; color: #263844; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #263844; }
            QWizard QLineEdit { background: #ffffff; color: #17212b; placeholder-text-color: #7a8994; border: 1px solid #aebfca; border-radius: 6px; padding: 7px 9px; }
            QWizard QPushButton { background: #ffffff; color: #263f52; border: 1px solid #aebfca; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
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
            QFrame#rdpWarningBanner, QFrame#sessionWarning { background: #413516; border-color: #a98438; }
            QLabel#rdpWarningTitle, QLabel#sessionWarningTitle { color: #ffdf9b; }
            QLabel#rdpWarningText, QLabel#sessionWarningText { color: #f4d59a; }
            QPushButton#warningDismissButton { color: #ffdf9b; border-color: #a98438; }
            QPushButton#warningDismissButton:hover { background: #5b481d; }
            QLineEdit, QComboBox, QDateEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; selection-background-color: #4f7897; selection-color: #ffffff; }
            QLineEdit#dashboardSearch, QComboBox#dashboardFilter, QLineEdit#pingInput { background: #1a2a35; color: #f1f6fa; border-color: #4c697a; }
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
            QMessageBox QPushButton, QDialogButtonBox QPushButton { background: #263d4b; color: #f3f8fb; border-color: #628196; }
            QMessageBox QPushButton:hover, QDialogButtonBox QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QMessageBox QPushButton:default, QDialogButtonBox QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QMessageBox QPushButton:default:hover, QDialogButtonBox QPushButton:default:hover { background: #6ca6c7; border-color: #b5d9ea; }
            QDialog QLineEdit, QDialog QComboBox, QDialog QDateEdit, QDialog QDateTimeEdit,
            QDialog QSpinBox, QDialog QTextEdit, QDialog QPlainTextEdit {
                background: #1a2a35;
                color: #f1f6fa;
                placeholder-text-color: #8fa6b5;
                border-color: #557386;
                selection-background-color: #4f7897;
                selection-color: #ffffff;
            }
            QDialog QLineEdit:read-only, QDialog QLineEdit:disabled {
                background: #22343f;
                color: #aebfca;
                border-color: #456172;
            }
            QDialog QTabWidget::pane { background: #1a2a35; border-color: #456172; }
            QDialog QTabBar::tab { background: #263b48; color: #c8d8e2; border-color: #456172; }
            QDialog QTabBar::tab:selected { background: #1a2a35; color: #ffffff; }
            QWizard, QWizardPage { background: #192833; color: #e7f0f5; }
            QWizard QLabel, QWizard QCheckBox, QWizard QRadioButton { color: #e7f0f5; }
            QWizard QLineEdit { background: #1a2a35; color: #f1f6fa; placeholder-text-color: #8fa6b5; border: 1px solid #557386; border-radius: 6px; padding: 7px 9px; }
            QWizard QLineEdit:disabled { background: #22343f; color: #aebfca; border-color: #456172; }
            QWizard QPushButton { background: #263d4b; color: #f3f8fb; border: 1px solid #628196; border-radius: 6px; padding: 7px 13px; min-width: 82px; font-weight: 600; }
            QWizard QPushButton:hover { background: #315164; border-color: #9ac3da; }
            QWizard QPushButton:default { background: #5b91b1; color: #ffffff; border-color: #8cc0db; }
            QWizard QPushButton:disabled { background: #22343f; color: #8095a3; border-color: #3d5868; }
            QCheckBox { color: #e7f0f5; }
            QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #789bae; background: #1a2a35; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #5f96b8; border-color: #8fc1dd; }
            QToolTip { background: #101820; color: #f3f7fa; border: 1px solid #5b788a; }
        """


__all__ = ["MainWindow"]
