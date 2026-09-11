"""Card based workstation overview used by the main dashboard."""

from __future__ import annotations

import locale
import re

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.design import Colors, Typography
from portal_app.ui.widgets.ping_tool import PingToolWidget
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from shared.enums import AgentStatus, ManualFlagType, SessionState


class WorkstationGlyph(QWidget):
    """Small monitor glyph drawn with Qt so no image asset is required."""

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.setFixedSize(42, 42)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(5, 6, 32, 24, 3, 3)
        painter.drawLine(21, 30, 21, 35)
        painter.drawLine(14, 36, 28, 36)
        painter.setBrush(self.color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(30, 9, 4, 4)


class WorkstationCard(QFrame):
    """A workstation tile with its state and primary actions."""

    selected = Signal(Workstation)
    ping_completed = Signal(str)
    connect_requested = Signal(Workstation)
    account_selected = Signal(Workstation, str)
    account_add_requested = Signal(Workstation)

    def __init__(
        self,
        workstation: Workstation,
        user: User,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstation = workstation
        self.user = user
        self.ping_process: QProcess | None = None
        self.setObjectName("workstationCard")
        self.setStyleSheet(f"QFrame#workstationCard {{ border: 3px solid {self._accent_color().name()}; }}")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(250, 306)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._create_ui()

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(WorkstationGlyph(self._accent_color()))

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        name = QLabel(self.workstation.display_name)
        name.setObjectName("cardTitle")
        name.setFont(Typography.get_font(16, Typography.FONT_WEIGHT_SEMIBOLD))
        title_box.addWidget(name)
        hostname = QLabel(
            self.workstation.hostname
            or self.workstation.fqdn
            or self.workstation.ip_address
            or "Kein Verbindungsziel"
        )
        hostname.setObjectName("cardMeta")
        title_box.addWidget(hostname)
        heading.addLayout(title_box, 1)
        self.ping_result = QLabel("")
        self.ping_result.setObjectName("cardMeta")
        self.ping_result.setToolTip("Letztes ICMP-Ping-Ergebnis; unabhängig vom Agentstatus")
        heading.addWidget(self.ping_result, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(heading)

        layout.addSpacing(20)
        location = QLabel(
            f"{self.workstation.site or 'Ohne Standort'}  ·  "
            f"{self.workstation.description or 'Workstation'}"
        )
        location.setObjectName("cardMeta")
        location.setWordWrap(True)
        layout.addWidget(location)
        layout.addSpacing(14)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_dot = QLabel("●")
        status_dot.setStyleSheet(f"color: {self._accent_color().name()}; font-size: 12px;")
        status_row.addWidget(status_dot)
        status = QLabel(self._status_text())
        status.setToolTip(self.workstation.agent_diagnostic)
        status.setObjectName("cardStatus")
        status_row.addWidget(status)
        status_row.addStretch()
        layout.addLayout(status_row)

        session = QLabel(self._session_text())
        session.setToolTip(self.workstation.agent_diagnostic)
        session.setObjectName("cardMeta")
        session.setContentsMargins(20, 2, 0, 0)
        layout.addWidget(session)
        if self.workstation.reservation_message:
            reservation = QLabel(self.workstation.reservation_message)
            reservation.setObjectName("cardStatus")
            reservation.setWordWrap(True)
            layout.addWidget(reservation)
        layout.addStretch()

        layout.addSpacing(10)
        self.account_selector = LoginAccountSelector(self.workstation, self.user, self)
        self.account_selector.account_selected.connect(self.account_selected)
        self.account_selector.add_requested.connect(self.account_add_requested)
        layout.addWidget(self.account_selector)
        layout.addSpacing(12)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        details = QPushButton("Details")
        details.setObjectName("cardSecondaryButton")
        details.clicked.connect(lambda: self.selected.emit(self.workstation))
        action_row.addWidget(details)
        self.ping_btn = QPushButton("Ping")
        self.ping_btn.setObjectName("cardSecondaryButton")
        self.ping_btn.setToolTip("Erreichbarkeit des konfigurierten RDP-Ziels pr\u00fcfen")
        self.ping_btn.clicked.connect(self._ping)
        action_row.addWidget(self.ping_btn)
        connect = QPushButton("Wiederverbinden" if self.workstation.matching_sessions(self.user.get_rdp_username()) else "Verbinden")
        connect.setObjectName("cardPrimaryButton")
        connect.setEnabled(self.workstation.can_connect(self.user.get_rdp_username()) or self.workstation.can_choose_session())
        if not self.workstation.can_connect(self.user.get_rdp_username()):
            connect.setText("Reserviert" if self.workstation.reservation_block_reason else self.workstation.get_status_display())
            if self.workstation.can_choose_session():
                connect.setText("Sitzung öffnen …")
        connect.setToolTip(self.workstation.reservation_message)
        connect.clicked.connect(lambda: self.connect_requested.emit(self.workstation))
        action_row.addWidget(connect, 1)
        layout.addLayout(action_row)

    def _ping(self) -> None:
        """Ping the same target that the RDP profile will use."""
        if self.ping_process is not None:
            return
        try:
            target, _ = self.workstation.get_connection_target()
        except ValueError:
            self.ping_btn.setText("Kein Ziel")
            self.ping_btn.setEnabled(False)
            return
        self.ping_btn.setText("Pr\u00fcfe \u2026")
        self.ping_btn.setEnabled(False)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        self.ping_process = process
        process.finished.connect(self._on_ping_finished)
        process.errorOccurred.connect(self._on_ping_error)
        process.start("ping", ["-n", "1", "-w", "2000", target])

    def _on_ping_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        success = exit_code == 0 and exit_status == QProcess.NormalExit
        latency = self._ping_latency() if success else None
        result = f"{latency} ms" if latency else ("Antwort" if success else "Keine Ping-Antwort")
        self.ping_result.setText(result)
        self.ping_completed.emit(result)
        self.ping_btn.setText("Ping")
        self.ping_btn.setProperty("pingOk", success)
        self.ping_btn.style().unpolish(self.ping_btn)
        self.ping_btn.style().polish(self.ping_btn)
        self._finish_ping()

    def _on_ping_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.FailedToStart:
            self.ping_result.setText("Ping nicht verfügbar")
            self.ping_completed.emit("Ping nicht verfügbar")
            self.ping_btn.setText("Ping")
            self.ping_btn.setProperty("pingOk", False)
            self._finish_ping()

    def _ping_latency(self) -> str | None:
        if not self.ping_process:
            return None
        output = bytes(self.ping_process.readAllStandardOutput()).decode(
            locale.getpreferredencoding(False), errors="replace"
        )
        match = re.search(r"(?:zeit|time)([=<])\s*(\d+)\s*ms", output, re.IGNORECASE)
        return (("<" if match.group(1) == "<" else "") + match.group(2)) if match else None

    def _finish_ping(self) -> None:
        self.ping_btn.setEnabled(True)
        if self.ping_process:
            self.ping_process.deleteLater()
        self.ping_process = None

    def _accent_color(self) -> QColor:
        ws = self.workstation
        if not ws.enabled or ws.agent_status == AgentStatus.OFFLINE:
            return Colors.text_muted
        if ws.manual_flag_type == ManualFlagType.BLOCKED or ws.agent_status == AgentStatus.ERROR:
            return Colors.error
        if ws.manual_flag_type == ManualFlagType.MAINTENANCE or ws.agent_status == AgentStatus.STALE:
            return Colors.warning
        if ws.has_active_session():
            return Colors.info
        if ws.manual_flag_type == ManualFlagType.CALCULATION_RUNNING:
            return Colors.info
        return Colors.success

    def _status_text(self) -> str:
        state = self.workstation.get_status_display()
        return f"Agent: {self.workstation.get_agent_status_display()} · {state}"

    def _session_text(self) -> str:
        user = self.workstation.get_session_user_display()
        if user != "-":
            return f"Belegt von {user}"
        if self.workstation.current_session_state == SessionState.DISCONNECTED:
            return "Sitzung getrennt"
        if self.workstation.agent_status != AgentStatus.ONLINE:
            if self.workstation.agent_last_seen_utc:
                return "Agent-Meldung prüfen · siehe Diagnose"
            return "Agentstatus fehlt · Ping = Netzwerk"
        return "Keine Windows-Sitzung" if self.workstation.reservation_message else "Frei und verfügbar"

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.workstation)
        super().mousePressEvent(event)


class AddWorkstationCard(QFrame):
    """Dashed tile mirroring the add affordance in the paper sketch."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("addWorkstationCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(250, 306)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)
        plus = QLabel("+")
        plus.setObjectName("addCardPlus")
        plus.setAlignment(Qt.AlignCenter)
        layout.addWidget(plus)
        title = QLabel("Maschine hinzufügen")
        title.setObjectName("addCardTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Neue RDP-Verbindung anlegen")
        subtitle.setObjectName("cardMeta")
        subtitle.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class WorkstationCardsWidget(QWidget):
    """Responsive, searchable card grid for workstations."""

    workstation_selected = Signal(Workstation)
    connect_requested = Signal(Workstation)
    account_selected = Signal(Workstation, str)
    account_add_requested = Signal(Workstation)
    add_requested = Signal()
    refresh_requested = Signal()
    agent_diagnostics_requested = Signal()

    def __init__(
        self,
        workstations: list[Workstation],
        user: User,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstations = workstations
        self.user = user
        self._cards: list[QWidget] = []
        self._columns = 0
        self._create_ui()
        self._rebuild_grid()

    def _create_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)
        agent_row = QHBoxLayout()
        self.agent_channel_status = QLabel("Agent-Dateien werden geprüft …")
        self.agent_channel_status.setObjectName("cardMeta")
        self.agent_channel_status.setWordWrap(True)
        agent_row.addWidget(self.agent_channel_status, 1)
        self.agent_diagnostics_button = QPushButton("Agent-Diagnose")
        self.agent_diagnostics_button.setObjectName("toolbarButton")
        self.agent_diagnostics_button.clicked.connect(self.agent_diagnostics_requested)
        agent_row.addWidget(self.agent_diagnostics_button)
        root.addLayout(agent_row)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setObjectName("dashboardSearch")
        self.search.setPlaceholderText("Maschine suchen …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild_grid)
        toolbar.addWidget(self.search, 1)
        refresh = QPushButton("Aktualisieren")
        refresh.setObjectName("toolbarButton")
        refresh.clicked.connect(self.refresh_requested)
        toolbar.addWidget(refresh)
        root.addLayout(toolbar)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.site_filter = QComboBox()
        self.site_filter.setObjectName("dashboardFilter")
        self.site_filter.addItem("Alle Standorte", "")
        for site in sorted({ws.site for ws in self.workstations if ws.site}):
            self.site_filter.addItem(site, site)
        self.site_filter.currentIndexChanged.connect(self._rebuild_grid)
        filters.addWidget(self.site_filter)
        self.agent_filter = QComboBox()
        self.agent_filter.setObjectName("dashboardFilter")
        self.agent_filter.addItem("Alle Agentstatus", "")
        self.agent_filter.addItem("Online", "online")
        self.agent_filter.addItem("Veraltet", "stale")
        self.agent_filter.addItem("Offline", "offline")
        self.agent_filter.addItem("Fehler", "error")
        self.agent_filter.currentIndexChanged.connect(self._rebuild_grid)
        filters.addWidget(self.agent_filter)
        self.flag_filter = QComboBox()
        self.flag_filter.setObjectName("dashboardFilter")
        self.flag_filter.addItem("Alle Kennzeichnungen", "")
        self.flag_filter.addItem("Ohne Flag", "none")
        self.flag_filter.addItem("Berechnung läuft", "calculation_running")
        self.flag_filter.addItem("Wartung", "maintenance")
        self.flag_filter.addItem("Gesperrt", "blocked")
        self.flag_filter.currentIndexChanged.connect(self._rebuild_grid)
        filters.addWidget(self.flag_filter)
        self.user_filter = QComboBox()
        self.user_filter.setObjectName("dashboardFilter")
        self.user_filter.addItem("Alle Benutzer", "")
        self._populate_user_filter()
        self.user_filter.currentIndexChanged.connect(self._rebuild_grid)
        filters.addWidget(self.user_filter)
        filters.addStretch()
        root.addLayout(filters)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("machineScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("gridHost")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 4, 8, 12)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)
        ping_row = QHBoxLayout()
        ping_row.addStretch()
        self.ping_tool = PingToolWidget()
        ping_row.addWidget(self.ping_tool)
        root.addLayout(ping_row)

    def _populate_user_filter(self) -> None:
        users = sorted({ws.current_session_user for ws in self.workstations if ws.current_session_user})
        for user in users:
            self.user_filter.addItem(user, user)

    def _filtered_workstations(self) -> list[Workstation]:
        query = self.search.text().strip().lower()
        site = self.site_filter.currentData()
        agent = self.agent_filter.currentData()
        flag = self.flag_filter.currentData()
        session_user = self.user_filter.currentData()
        result = []
        for workstation in self.workstations:
            haystack = " ".join(
                filter(
                    None,
                    [
                        workstation.display_name,
                        workstation.hostname,
                        workstation.site,
                        workstation.description,
                    ],
                )
            ).lower()
            if query and query not in haystack:
                continue
            if site and workstation.site != site:
                continue
            if agent and workstation.agent_status.value != agent:
                continue
            if flag and workstation.manual_flag_type.value != flag:
                continue
            if session_user and workstation.current_session_user != session_user:
                continue
            result.append(workstation)
        return result

    def _rebuild_grid(self) -> None:
        if not hasattr(self, "_ping_results"):
            self._ping_results: dict[str, str] = {}
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._cards.clear()
        columns = self._column_count()
        self._columns = columns
        items: list[QWidget] = []
        for workstation in self._filtered_workstations():
            card = WorkstationCard(workstation, self.user)
            card.ping_result.setText(self._ping_results.get(workstation.workstation_id, ""))
            card.ping_completed.connect(lambda result, key=workstation.workstation_id: self._ping_results.__setitem__(key, result))
            card.selected.connect(self.workstation_selected)
            card.connect_requested.connect(self.connect_requested)
            card.account_selected.connect(self.account_selected)
            card.account_add_requested.connect(self.account_add_requested)
            items.append(card)
        add_card = AddWorkstationCard()
        add_card.clicked.connect(self.add_requested)
        items.append(add_card)
        for index, card in enumerate(items):
            row, column = divmod(index, columns)
            self.grid.addWidget(card, row, column)
            self.grid.setColumnStretch(column, 1)
            self._cards.append(card)

    def _column_count(self) -> int:
        width = max(self.scroll.viewport().width(), self.width())
        return max(1, min(4, width // 285))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        columns = self._column_count()
        if self._columns and columns != self._columns:
            self._rebuild_grid()

    def set_workstations(self, workstations: list[Workstation]) -> None:
        self.workstations = workstations
        selected_site = self.site_filter.currentData()
        self.site_filter.blockSignals(True)
        self.site_filter.clear()
        self.site_filter.addItem("Alle Standorte", "")
        for site in sorted({ws.site for ws in self.workstations if ws.site}):
            self.site_filter.addItem(site, site)
        selected_index = self.site_filter.findData(selected_site)
        self.site_filter.setCurrentIndex(max(0, selected_index))
        self.site_filter.blockSignals(False)
        selected_user = self.user_filter.currentData()
        self.user_filter.blockSignals(True)
        self.user_filter.clear()
        self.user_filter.addItem("Alle Benutzer", "")
        self._populate_user_filter()
        self.user_filter.setCurrentIndex(max(0, self.user_filter.findData(selected_user)))
        self.user_filter.blockSignals(False)
        self._rebuild_grid()


__all__ = ["WorkstationCardsWidget", "WorkstationCard", "AddWorkstationCard"]
