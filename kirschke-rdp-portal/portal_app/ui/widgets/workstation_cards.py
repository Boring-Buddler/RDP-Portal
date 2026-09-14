"""Card based workstation overview used by the main dashboard."""

from __future__ import annotations

import locale
import re

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
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
from portal_app.ui.design import Typography
from portal_app.ui.machine_actions import (
    SORT_ORDER,
    css_color,
    describe_actions,
    machine_state,
    state_border_width,
    state_color,
)
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from portal_app.ui.widgets.ping_tool import PingToolWidget
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox as QComboBox
from portal_app.ui.widgets.status_legend import StatusLegend
from shared.enums import AgentStatus, SessionState


class WorkstationGlyph(QWidget):
    """Small monitor glyph drawn with Qt so no image asset is required."""

    def __init__(self, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self.setFixedSize(42, 42)

    def set_color(self, color: QColor) -> None:
        if color != self.color:
            self.color = color
            self.update()

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
    logoff_requested = Signal(Workstation)
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
        self._apply_card_accent()
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(250, 372)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._create_ui()

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.glyph = WorkstationGlyph(self._accent_color())
        heading.addWidget(self.glyph)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self.name_label = QLabel(self.workstation.display_name)
        self.name_label.setObjectName("cardTitle")
        self.name_label.setFont(Typography.heading_3())
        title_box.addWidget(self.name_label)
        self.hostname_label = QLabel(
            self.workstation.hostname
            or self.workstation.fqdn
            or self.workstation.ip_address
            or "Kein Verbindungsziel"
        )
        self.hostname_label.setObjectName("cardMeta")
        title_box.addWidget(self.hostname_label)
        heading.addLayout(title_box, 1)
        self.ping_result = QLabel("")
        self.ping_result.setObjectName("cardMeta")
        self.ping_result.setToolTip("Letztes ICMP-Ping-Ergebnis; unabhängig vom Agentstatus")
        heading.addWidget(self.ping_result, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(heading)

        layout.addSpacing(20)
        self.location_label = QLabel(
            f"{self.workstation.site or 'Ohne Standort'}  ·  "
            f"{self.workstation.description or 'Workstation'}"
        )
        self.location_label.setObjectName("cardMeta")
        self.location_label.setWordWrap(True)
        layout.addWidget(self.location_label)
        layout.addSpacing(14)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {css_color(self._accent_color())}; font-size: 12px;")
        status_row.addWidget(self.status_dot)
        self.status_label = QLabel(self._status_text())
        self.status_label.setToolTip(self.workstation.agent_diagnostic)
        self.status_label.setObjectName("cardStatus")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        self.source_label = QLabel(self.workstation.get_agent_source_display())
        self.source_label.setObjectName("cardMeta")
        self.source_label.setContentsMargins(20, 1, 0, 0)
        layout.addWidget(self.source_label)
        self.session_label = QLabel(self._session_text())
        self.session_label.setToolTip(self.workstation.agent_diagnostic)
        self.session_label.setObjectName("cardMeta")
        self.session_label.setContentsMargins(20, 2, 0, 0)
        layout.addWidget(self.session_label)
        self.reservation_label = QLabel(self.workstation.reservation_message)
        self.reservation_label.setObjectName("cardStatus")
        self.reservation_label.setWordWrap(True)
        self.reservation_label.setVisible(bool(self.workstation.reservation_message))
        layout.addWidget(self.reservation_label)
        layout.addStretch()

        layout.addSpacing(10)
        self.account_selector = LoginAccountSelector(self.workstation, self.user, self)
        self.account_selector.account_selected.connect(self.account_selected)
        self.account_selector.add_requested.connect(self.account_add_requested)
        layout.addWidget(self.account_selector)
        layout.addSpacing(12)
        secondary_row = QHBoxLayout()
        secondary_row.setSpacing(8)
        details = QPushButton("Details")
        details.setObjectName("cardSecondaryButton")
        details.clicked.connect(lambda: self.selected.emit(self.workstation))
        secondary_row.addWidget(details, 1)
        self.ping_btn = QPushButton("Ping")
        self.ping_btn.setObjectName("cardSecondaryButton")
        self.ping_btn.setToolTip("Erreichbarkeit des konfigurierten RDP-Ziels pr\u00fcfen")
        self.ping_btn.clicked.connect(self._ping)
        secondary_row.addWidget(self.ping_btn, 1)
        layout.addLayout(secondary_row)
        layout.addSpacing(8)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.connect_btn = QPushButton()
        self.connect_btn.setObjectName("cardPrimaryButton")
        self.connect_btn.clicked.connect(lambda: self.connect_requested.emit(self.workstation))
        action_row.addWidget(self.connect_btn, 1)
        self.logoff_btn = QPushButton("Abmelden")
        self.logoff_btn.setObjectName("dangerButton")
        self.logoff_btn.setToolTip("Windows prüft Sitzung, Anmeldezeit und Benutzerkennung vor der Abmeldung.")
        self.logoff_btn.clicked.connect(lambda: self.logoff_requested.emit(self.workstation))
        action_row.addWidget(self.logoff_btn)
        layout.addLayout(action_row)
        self.refresh_status()

    def set_workstation(self, workstation: Workstation, user: User) -> None:
        self.workstation = workstation
        self.user = user
        self.name_label.setText(workstation.display_name)
        self.hostname_label.setText(
            workstation.hostname or workstation.fqdn or workstation.ip_address or "Kein Verbindungsziel"
        )
        self.location_label.setText(
            f"{workstation.site or 'Ohne Standort'}  ·  {workstation.description or 'Workstation'}"
        )
        self.account_selector.set_workstation(workstation, user)
        self.refresh_status()

    def refresh_status(self) -> None:
        accent = self._accent_color()
        self._apply_card_accent()
        self.glyph.set_color(accent)
        # css_color rather than QColor.name(), which would drop the emphasis alpha.
        self.status_dot.setStyleSheet(f"color: {css_color(accent)}; font-size: 12px;")
        self.status_label.setText(self._status_text())
        self.status_label.setToolTip(self.workstation.agent_diagnostic)
        self.source_label.setText(self.workstation.get_agent_source_display())
        self.source_label.setToolTip(self.workstation.agent_diagnostic)
        self.session_label.setText(self._session_text())
        self.session_label.setToolTip(self.workstation.agent_diagnostic)
        self.reservation_label.setText(self.workstation.reservation_message)
        self.reservation_label.setVisible(bool(self.workstation.reservation_message))

        from portal_app.rdp import has_active_rdp_session

        actions = describe_actions(
            self.workstation,
            self.user,
            window_open=has_active_rdp_session(self.workstation.workstation_id),
        )
        # The primary button is always shown. Hiding it while an own session was
        # connected used to leave a machine you are signed into with no way back.
        self.connect_btn.setVisible(True)
        self.connect_btn.setText(actions.primary_text)
        self.connect_btn.setEnabled(actions.primary_enabled)
        self.connect_btn.setToolTip(actions.primary_tooltip or self.workstation.reservation_message)
        self.logoff_btn.setVisible(actions.logoff_visible)
        self.logoff_btn.setEnabled(actions.logoff_enabled)
        self.logoff_btn.setToolTip(actions.logoff_tooltip)

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

    def _state(self):
        """The one state decides colour, weight and buttons alike."""
        from portal_app.rdp import has_active_rdp_session

        return machine_state(
            self.workstation,
            self.user,
            window_open=has_active_rdp_session(self.workstation.workstation_id),
        )

    def _accent_color(self) -> QColor:
        """The accent for border, glyph and status dot, emphasis included."""
        return state_color(self._state())

    def _apply_card_accent(self) -> None:
        state = self._state()
        accent, width = state_color(state), state_border_width(state)
        self.setStyleSheet(
            f"QFrame#workstationCard {{ border: {width}px solid {css_color(accent)}; }}"
        )

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
    logoff_requested = Signal(Workstation)
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
        footer = QHBoxLayout()
        footer.setSpacing(16)
        self.legend = StatusLegend()
        footer.addWidget(self.legend, 1)
        self.ping_tool = PingToolWidget()
        footer.addWidget(self.ping_tool, 0, Qt.AlignBottom)
        root.addLayout(footer)

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
        return sorted(
            result,
            key=lambda ws: (
                self._visual_priority(ws),
                ws.display_name.casefold(),
                ws.workstation_id.casefold(),
            ),
        )

    def _visual_priority(self, workstation: Workstation) -> int:
        """Sort by the same state that colours the card: free first, grey last."""
        from portal_app.rdp import has_active_rdp_session

        return SORT_ORDER[
            machine_state(
                workstation,
                self.user,
                window_open=has_active_rdp_session(workstation.workstation_id),
            )
        ]

    def _rebuild_grid(self) -> None:
        if not hasattr(self, "_ping_results"):
            self._ping_results: dict[str, str] = {}
        filtered = self._filtered_workstations()
        columns = self._column_count()
        existing_cards = [item for item in self._cards if isinstance(item, WorkstationCard)]
        if (
            self._columns == columns
            and [item.workstation.workstation_id for item in existing_cards]
            == [item.workstation_id for item in filtered]
        ):
            for card, workstation in zip(existing_cards, filtered, strict=True):
                card.set_workstation(workstation, self.user)
            return
        scroll_position = self.scroll.verticalScrollBar().value()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self._cards.clear()
        self._columns = columns
        items: list[QWidget] = []
        for workstation in filtered:
            card = WorkstationCard(workstation, self.user)
            card.ping_result.setText(self._ping_results.get(workstation.workstation_id, ""))
            card.ping_completed.connect(lambda result, key=workstation.workstation_id: self._ping_results.__setitem__(key, result))
            card.selected.connect(self.workstation_selected)
            card.connect_requested.connect(self.connect_requested)
            card.logoff_requested.connect(self.logoff_requested)
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
        self.scroll.verticalScrollBar().setValue(scroll_position)

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
        sites = sorted({ws.site for ws in self.workstations if ws.site})
        existing_sites = [self.site_filter.itemData(i) for i in range(1, self.site_filter.count())]
        if existing_sites != sites:
            self.site_filter.blockSignals(True)
            self.site_filter.clear()
            self.site_filter.addItem("Alle Standorte", "")
            for site in sites:
                self.site_filter.addItem(site, site)
            selected_index = self.site_filter.findData(selected_site)
            self.site_filter.setCurrentIndex(max(0, selected_index))
            self.site_filter.blockSignals(False)
        selected_user = self.user_filter.currentData()
        users = sorted({ws.current_session_user for ws in self.workstations if ws.current_session_user})
        existing_users = [self.user_filter.itemData(i) for i in range(1, self.user_filter.count())]
        if existing_users != users:
            self.user_filter.blockSignals(True)
            self.user_filter.clear()
            self.user_filter.addItem("Alle Benutzer", "")
            self._populate_user_filter()
            self.user_filter.setCurrentIndex(max(0, self.user_filter.findData(selected_user)))
            self.user_filter.blockSignals(False)
        self._rebuild_grid()


__all__ = ["WorkstationCardsWidget", "WorkstationCard", "AddWorkstationCard"]
