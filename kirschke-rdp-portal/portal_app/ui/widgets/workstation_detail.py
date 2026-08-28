"""Clean, actionable workstation detail page."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QProcess, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.session import SessionEvent
from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.flag_dialog import FlagDialog
from shared.enums import ManualFlagType


class WorkstationDetailWidget(QWidget):
    """Shows master data and keeps all machine actions in one action bar."""

    workstation_updated = Signal(Workstation)
    connect_requested = Signal(Workstation)
    diagnostics_requested = Signal(Workstation)
    edit_requested = Signal(Workstation)
    back_requested = Signal()

    def __init__(self, user: User, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.user = user
        self.workstation: Workstation | None = None
        self.ping_process: QProcess | None = None
        self.session_events: list[SessionEvent] = []
        self.value_labels: dict[str, QLabel] = {}
        self._create_ui()

    def _create_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.back_btn = QPushButton("← Maschinen")
        self.back_btn.setObjectName("toolbarButton")
        self.back_btn.clicked.connect(self.back_requested)
        header.addWidget(self.back_btn)
        header.addStretch()
        self.edit_btn = QPushButton("Daten bearbeiten")
        self.edit_btn.setObjectName("toolbarButton")
        self.edit_btn.clicked.connect(self._on_edit)
        header.addWidget(self.edit_btn)
        self.diagnostics_btn = QPushButton("RDP-Diagnose")
        self.diagnostics_btn.setObjectName("toolbarButton")
        self.diagnostics_btn.clicked.connect(self._on_diagnostics)
        header.addWidget(self.diagnostics_btn)
        self.connect_btn = QPushButton("RDP verbinden")
        self.connect_btn.setObjectName("cardPrimaryButton")
        self.connect_btn.clicked.connect(self._on_connect)
        header.addWidget(self.connect_btn)
        root.addLayout(header)

        self.session_warning = QFrame()
        self.session_warning.setObjectName("sessionWarning")
        warning_layout = QHBoxLayout(self.session_warning)
        warning_layout.setContentsMargins(16, 12, 16, 12)
        warning_layout.setSpacing(12)
        warning_icon = QLabel("!")
        warning_icon.setObjectName("sessionWarningIcon")
        warning_icon.setFixedSize(28, 28)
        warning_icon.setAlignment(Qt.AlignCenter)
        warning_layout.addWidget(warning_icon)
        warning_copy = QVBoxLayout()
        warning_copy.setSpacing(2)
        warning_title = QLabel("Zugang durch Windows-Sitzung belegt")
        warning_title.setObjectName("sessionWarningTitle")
        warning_copy.addWidget(warning_title)
        self.session_warning_text = QLabel()
        self.session_warning_text.setObjectName("sessionWarningText")
        self.session_warning_text.setWordWrap(True)
        warning_copy.addWidget(self.session_warning_text)
        warning_layout.addLayout(warning_copy, 1)
        self.session_warning.setVisible(False)
        root.addWidget(self.session_warning)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("detailScroll")
        content = QWidget()
        content.setObjectName("detailContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 8)
        content_layout.setSpacing(16)

        overview = QGridLayout()
        overview.setHorizontalSpacing(16)
        overview.setVerticalSpacing(16)
        overview.addWidget(
            self._info_card(
                "Stammdaten",
                (
                    ("name", "Name"),
                    ("id", "Maschinen-ID"),
                    ("site", "Standort"),
                    ("description", "Beschreibung"),
                ),
            ),
            0,
            0,
        )
        overview.addWidget(
            self._info_card(
                "Netzwerk",
                (
                    ("hostname", "Hostname"),
                    ("fqdn", "FQDN"),
                    ("ip", "IP-Adresse"),
                    ("subnet", "Subnetzmaske"),
                    ("network_gateway", "Standardgateway"),
                    ("dns", "DNS-Server"),
                ),
            ),
            0,
            1,
        )
        overview.addWidget(
            self._info_card(
                "Status und Sitzung",
                (
                    ("status", "Gesamtstatus"),
                    ("agent", "Agent"),
                    ("last_seen", "Zuletzt gesehen"),
                    ("session", "Sitzung"),
                    ("session_user", "Angemeldeter Benutzer"),
                ),
            ),
            1,
            0,
        )
        overview.addWidget(
            self._info_card(
                "RDP-Profil",
                (
                    ("connection_target", "Verbindungsziel"),
                    ("rdp_user", "Benutzername"),
                    ("rdp_gateway", "RD-Gateway"),
                    ("screen", "Anzeige"),
                    ("monitors", "Monitore"),
                    ("redirects", "Umleitungen"),
                    ("sso", "Entra SSO"),
                    ("server_identity", "ServeridentitÃ¤t"),
                ),
            ),
            1,
            1,
        )
        overview.setColumnStretch(0, 1)
        overview.setColumnStretch(1, 1)
        content_layout.addLayout(overview)

        history_card = QFrame()
        history_card.setObjectName("detailCard")
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(20, 18, 20, 18)
        history_title = QLabel("Sitzungshistorie")
        history_title.setObjectName("detailCardTitle")
        history_layout.addWidget(history_title)
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["Zeitpunkt", "Ereignis", "Benutzer", "Ergebnis"])
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSelectionMode(QTableWidget.NoSelection)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.setMaximumHeight(210)
        history_layout.addWidget(self.history_table)
        content_layout.addWidget(history_card)

        flag_card = QFrame()
        flag_card.setObjectName("detailCard")
        flag_layout = QHBoxLayout(flag_card)
        flag_layout.setContentsMargins(20, 18, 20, 18)
        flag_text = QVBoxLayout()
        flag_title = QLabel("Manuelle Kennzeichnung")
        flag_title.setObjectName("detailCardTitle")
        flag_text.addWidget(flag_title)
        self.flag_value = QLabel("Kein Flag gesetzt")
        self.flag_value.setObjectName("detailValue")
        flag_text.addWidget(self.flag_value)
        self.flag_reason = QLabel("–")
        self.flag_reason.setObjectName("detailMuted")
        self.flag_reason.setWordWrap(True)
        flag_text.addWidget(self.flag_reason)
        flag_layout.addLayout(flag_text, 1)

        self.ping_result = QLabel("Noch nicht geprüft")
        self.ping_result.setObjectName("detailMuted")
        flag_layout.addWidget(self.ping_result)
        self.ping_btn = QPushButton("Ping")
        self.ping_btn.setObjectName("toolbarButton")
        self.ping_btn.clicked.connect(self._on_ping)
        flag_layout.addWidget(self.ping_btn)
        self.set_flag_btn = QPushButton("Flag setzen")
        self.set_flag_btn.setObjectName("toolbarButton")
        self.set_flag_btn.clicked.connect(self._on_set_flag)
        flag_layout.addWidget(self.set_flag_btn)
        self.clear_flag_btn = QPushButton("Flag entfernen")
        self.clear_flag_btn.setObjectName("toolbarButton")
        self.clear_flag_btn.clicked.connect(self._on_clear_flag)
        flag_layout.addWidget(self.clear_flag_btn)
        content_layout.addWidget(flag_card)
        content_layout.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _info_card(self, title: str, rows: tuple[tuple[str, str], ...]) -> QFrame:
        card = QFrame()
        card.setObjectName("detailCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("detailCardTitle")
        layout.addWidget(heading)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("detailDivider")
        layout.addWidget(line)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for row, (key, label) in enumerate(rows):
            name = QLabel(label)
            name.setObjectName("detailLabel")
            value = QLabel("–")
            value.setObjectName("detailValue")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(name, row, 0, Qt.AlignTop)
            grid.addWidget(value, row, 1, Qt.AlignTop)
            grid.setColumnStretch(1, 1)
            self.value_labels[key] = value
        layout.addLayout(grid)
        layout.addStretch()
        return card

    def set_user(self, user: User) -> None:
        self.user = user
        self._update_ui()

    def set_workstation(self, workstation: Workstation) -> None:
        self.workstation = workstation
        self._update_ui()

    def set_session_events(self, events: list[SessionEvent]) -> None:
        self.session_events = sorted(events, key=lambda event: event.timestamp_utc, reverse=True)
        self.history_table.setRowCount(len(self.session_events))
        for row, event in enumerate(self.session_events):
            values = (
                event.timestamp_utc.strftime("%d.%m.%Y · %H:%M:%S"),
                event.get_display_type(),
                event.session_user_upn or event.actor_upn or "–",
                event.get_display_result(),
            )
            for column, value in enumerate(values):
                self.history_table.setItem(row, column, QTableWidgetItem(value))
        self.history_table.resizeColumnToContents(0)
        self.history_table.resizeColumnToContents(2)
        self.history_table.resizeColumnToContents(3)

    def _update_ui(self) -> None:
        if not self.workstation:
            return
        ws = self.workstation
        profile = ws.get_rdp_profile(self.user.get_rdp_username())
        if ws.entra_sso_enabled and not profile.effective_entra_sso_enabled():
            sso_status = "Webkonto deaktiviert (IP-Ziel)"
        elif profile.effective_entra_sso_enabled():
            sso_status = "Entra-Webkonto aktiv"
        else:
            sso_status = "Klassische Windows-Anmeldung"
        values = {
            "name": ws.display_name,
            "id": ws.workstation_id,
            "site": ws.site or "–",
            "description": ws.description or "–",
            "hostname": ws.hostname or "–",
            "fqdn": ws.fqdn or "–",
            "ip": ws.ip_address or "–",
            "subnet": ws.subnet_mask or "–",
            "network_gateway": ws.default_gateway or "–",
            "dns": ws.dns_server or "–",
            "status": ws.get_status_display(),
            "agent": ws.get_agent_status_display(),
            "last_seen": self._format_datetime(ws.agent_last_seen_utc),
            "session": ws.current_session_state.value.replace("_", " ").title(),
            "session_user": ws.get_session_user_display(),
            "connection_target": ws.get_connection_target_display(),
            "rdp_user": ws.username_hint or self.user.get_rdp_username() or "Beim Start abfragen",
            "rdp_gateway": ws.gateway_hostname or "Direkte Verbindung",
            "screen": f"{ws.screen_mode or 'fullscreen'} · {ws.resolution or 'automatisch'}",
            "monitors": "Alle Monitore" if ws.use_all_monitors else "Ein Monitor",
            "redirects": self._redirects(ws),
            "sso": sso_status,
            "server_identity": (
                "Vertrauensausnahme aktiv"
                if ws.trust_unverified_server
                else "Windows prÃ¼ft und warnt bei Bedarf"
            ),
        }
        for key, value in values.items():
            self.value_labels[key].setText(value)
        if ws.manual_flag_type == ManualFlagType.NONE:
            self.flag_value.setText("Kein Flag gesetzt")
            self.flag_reason.setText("Die Maschine ist nicht manuell gekennzeichnet.")
        else:
            self.flag_value.setText(ws.get_status_display())
            self.flag_reason.setText(ws.manual_flag_reason or "Ohne Begründung")
        self.connect_btn.setEnabled(ws.can_connect())
        self.connect_btn.setText("RDP verbinden" if ws.can_connect() else "Zugang belegt")
        self.session_warning.setVisible(ws.has_active_session())
        if ws.has_active_session():
            self.session_warning_text.setText(
                f"Status: {ws.get_status_display()} · Benutzer: {ws.get_session_user_display()}. "
                "Eine getrennte Sitzung bleibt möglicherweise angemeldet. Vor einer neuen Verbindung bitte abmelden."
            )
        self.set_flag_btn.setEnabled(ws.can_set_flag(ManualFlagType.CALCULATION_RUNNING, self.user.is_admin))
        is_owner = ws.manual_flag_set_by_upn == self.user.upn
        self.clear_flag_btn.setEnabled(ws.is_blocked() and ws.can_clear_flag(self.user.is_admin, is_owner))
        self.ping_result.setText("Noch nicht geprüft")

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        return value.strftime("%d.%m.%Y · %H:%M") if value else "Noch nie"

    @staticmethod
    def _redirects(ws: Workstation) -> str:
        names = []
        if ws.redirect_clipboard:
            names.append("Zwischenablage")
        if ws.redirect_drives:
            names.append("Laufwerke")
        if ws.redirect_printers:
            names.append("Drucker")
        if ws.redirect_audio:
            names.append("Audio")
        return ", ".join(names) if names else "Keine"

    @Slot()
    def _on_edit(self) -> None:
        if self.workstation:
            self.edit_requested.emit(self.workstation)

    @Slot()
    def _on_connect(self) -> None:
        if self.workstation:
            self.connect_requested.emit(self.workstation)

    @Slot()
    def _on_diagnostics(self) -> None:
        if self.workstation:
            self.diagnostics_requested.emit(self.workstation)

    @Slot()
    def _on_set_flag(self) -> None:
        if not self.workstation:
            return
        dialog = FlagDialog(self.workstation, self.user, self)
        if dialog.exec() == FlagDialog.Accepted:
            self._update_ui()
            self.workstation_updated.emit(self.workstation)

    @Slot()
    def _on_clear_flag(self) -> None:
        if not self.workstation:
            return
        self.workstation.manual_flag_type = ManualFlagType.NONE
        self.workstation.manual_flag_reason = None
        self.workstation.manual_flag_project = None
        self.workstation.manual_flag_set_by_upn = None
        self.workstation.manual_flag_set_by_object_id = None
        self.workstation.manual_flag_set_at_utc = None
        self._update_ui()
        self.workstation_updated.emit(self.workstation)

    @Slot()
    def _on_ping(self) -> None:
        if not self.workstation or self.ping_process is not None:
            return
        target = self.workstation.ip_address or self.workstation.fqdn or self.workstation.hostname
        self.ping_result.setText(f"Prüfe {target} …")
        self.ping_btn.setEnabled(False)
        process = QProcess(self)
        self.ping_process = process
        process.finished.connect(self._on_ping_finished)
        process.errorOccurred.connect(self._on_ping_error)
        process.start("ping", ["-n", "1", "-w", "1500", target])

    def _on_ping_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        success = exit_code == 0 and exit_status == QProcess.NormalExit
        self.ping_result.setText("Erreichbar" if success else "Nicht erreichbar")
        self.ping_result.setProperty("pingOk", success)
        self.ping_result.style().unpolish(self.ping_result)
        self.ping_result.style().polish(self.ping_result)
        self.ping_btn.setEnabled(True)
        if self.ping_process:
            self.ping_process.deleteLater()
        self.ping_process = None

    def _on_ping_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self.ping_result.setText("Ping konnte nicht gestartet werden")
            self.ping_btn.setEnabled(True)
            if self.ping_process:
                self.ping_process.deleteLater()
            self.ping_process = None


__all__ = ["WorkstationDetailWidget"]
