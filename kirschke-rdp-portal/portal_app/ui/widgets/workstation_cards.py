"""Card based workstation overview used by the main dashboard."""

from __future__ import annotations

import locale
import re

from PySide6.QtCore import QProcess, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
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
    state_is_dashed,
    state_secondary_color,
)
from portal_app.ui.widgets.login_account_selector import LoginAccountSelector
from portal_app.ui.widgets.ping_tool import PingToolWidget
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox as QComboBox
from portal_app.ui.widgets.status_legend import StatusLegend
from shared.enums import AgentStatus, SessionState

#: Die Schnellauswahl auf der Karte. "Vollbild" ist der Standard und traegt
#: bewusst keine Aufloesung: mstsc nimmt dann den ganzen Bildschirm, egal wie
#: gross er ist. Die uebrigen Werte decken die Bildschirme ab, die hier
#: vorkommen; alles Weitere steht weiterhin in den Maschinendetails.
CARD_RESOLUTIONS = (
    ("Vollbild", None),
    ("3840 x 2160 (4K)", "3840x2160"),
    ("2560 x 1440 (2K)", "2560x1440"),
    ("1920 x 1080 (Full HD)", "1920x1080"),
    ("1600 x 900", "1600x900"),
    ("1366 x 768", "1366x768"),
    ("1280 x 720", "1280x720"),
)


def native_screen_size() -> tuple[int, int] | None:
    """The primary screen in real pixels, or ``None`` when it cannot be read.

    ``QScreen.size()`` counts logical pixels, so on a display running at 150 %
    it reports 1280x720 for a Full HD panel. The device pixel ratio converts
    that back to what the panel can actually show, which is the number an RDP
    session has to fit into.
    """
    from PySide6.QtGui import QGuiApplication

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    size = screen.size()
    ratio = screen.devicePixelRatio() or 1.0
    width, height = round(size.width() * ratio), round(size.height() * ratio)
    return (width, height) if width > 0 and height > 0 else None


def offered_resolutions(
    native: tuple[int, int] | None = None,
) -> tuple[tuple[str, str | None], ...]:
    """The quick-select entries that this screen can actually display.

    Offering 4K on a Full HD laptop would hand out a session larger than the
    window it has to live in -- the remote desktop is then only reachable by
    scrolling. So anything above the panel drops out, and the panel's own size
    joins the list when it is not one of the standard steps, which is what makes
    "as large as this screen allows" selectable at all.

    Without a readable screen the full list is offered rather than none.
    """
    native = native if native is not None else native_screen_size()
    if native is None:
        return CARD_RESOLUTIONS
    limit_width, limit_height = native

    def fits(value: str | None) -> bool:
        if value is None:
            return True
        width, _, height = value.partition("x")
        return int(width) <= limit_width and int(height) <= limit_height

    entries = [entry for entry in CARD_RESOLUTIONS if fits(entry[1])]
    exact = f"{limit_width}x{limit_height}"
    if not any(value == exact for _, value in entries):
        # Direkt hinter "Vollbild": es ist die groesste waehlbare Groesse.
        entries.insert(1, (f"{limit_width} x {limit_height} (Bildschirm)", exact))
    return tuple(entries)

#: Seitenverhaeltnis der Karte. Ohne Obergrenze zieht eine einzelne Maschine
#: die Kachel ueber die ganze Fensterbreite, was neben einem Raster aus
#: mehreren Karten wie ein Fehler aussieht.
CARD_ASPECT = 4 / 3

#: Hoehe der Karte. Zusammen mit CARD_ASPECT ergibt sie die Breite.
CARD_HEIGHT = 384
CARD_WIDTH = round(CARD_HEIGHT * CARD_ASPECT)

#: Abstand zwischen zwei Karten, hier und im Raster derselbe Wert.
CARD_GAP = 18


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
    #: (Maschine, Aufloesung oder None fuer Vollbild, alle Monitore)
    display_settings_changed = Signal(Workstation, object, bool)
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
        # Festes 4:3. Vorher war die Karte horizontal dehnbar: bei wenigen
        # Maschinen zog sich eine einzelne Kachel ueber das ganze Fenster und
        # sah neben einem Raster aus mehreren wie ein Fehler aus.
        self.setFixedSize(CARD_WIDTH, CARD_HEIGHT)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
        # Der Standort, nicht die Verbindungsadresse: die ist bei fast jeder
        # Maschine mit dem Anzeigenamen identisch, sodass hier zweimal dasselbe
        # stand. Wo die Maschine steht, beantwortet die Karte sonst nirgends
        # auf den ersten Blick.
        self.site_label = QLabel(self._site_text(self.workstation))
        self.site_label.setObjectName("cardMeta")
        title_box.addWidget(self.site_label)
        heading.addLayout(title_box, 1)
        heading.addLayout(self._build_quick_settings(), 0)
        layout.addLayout(heading)

        layout.addSpacing(20)
        self.location_label = QLabel(self._description_text(self.workstation))
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
        self.site_label.setText(self._site_text(workstation))
        self.location_label.setText(self._description_text(workstation))
        self._load_quick_settings(workstation)
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

    #: Laenge eines Strichs im gestrichelten Rand, in Vielfachen der Randbreite.
    DASH_LENGTH = 3.0

    #: Eckenradius des Kartenrahmens, gleich dem Wert im Stylesheet.
    CORNER_RADIUS = 11

    def _apply_card_accent(self) -> None:
        state = self._state()
        accent, width = state_color(state), state_border_width(state)
        if state_is_dashed(state):
            # Zwei Farben in einem Rand kann ein Stylesheet nicht. Der Rahmen
            # wird deshalb transparent gehalten -- gleiche Breite, damit sich am
            # Inhalt nichts verschiebt -- und in paintEvent selbst gezeichnet.
            self.setStyleSheet(
                f"QFrame#workstationCard {{ border: {width}px solid transparent; }}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#workstationCard {{ border: {width}px solid {css_color(accent)}; }}"
            )

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw the two-colour dashed border for a foreign, disconnected session.

        Two passes over the same rounded rectangle: the first lays down the
        violet dashes, the second the orange ones, offset by one dash so they
        interleave instead of overprinting.
        """
        super().paintEvent(event)
        state = self._state()
        if not state_is_dashed(state):
            return
        width = state_border_width(state)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Auf die Mitte der Randbreite einruecken, sonst liegt die halbe Linie
        # ausserhalb der Karte und wird abgeschnitten.
        inset = width / 2
        # QRectF, weil die Einrueckung eine halbe Randbreite ist und QRect
        # nur ganze Pixel kennt.
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        dash = self.DASH_LENGTH
        for color, offset in (
            (state_color(state), 0.0),
            (state_secondary_color(state), dash),
        ):
            pen = QPen(color, width)
            pen.setDashPattern([dash, dash])
            pen.setDashOffset(offset)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, self.CORNER_RADIUS, self.CORNER_RADIUS)
        painter.end()

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

    def _build_quick_settings(self) -> QVBoxLayout:
        """Resolution and multi-monitor choice, right beside name and site.

        Both settings also live in the machine details, but they are the two a
        person changes right before connecting -- and a full round trip through
        the edit dialog for a screen size is out of proportion to the change.
        """
        box = QVBoxLayout()
        box.setSpacing(4)
        self.ping_result = QLabel("")
        self.ping_result.setObjectName("cardMeta")
        self.ping_result.setAlignment(Qt.AlignRight)
        self.ping_result.setToolTip("Letztes ICMP-Ping-Ergebnis; unabhängig vom Agentstatus")
        box.addWidget(self.ping_result)
        self.resolution = QComboBox()
        self.resolution.setObjectName("cardQuickSelect")
        self.resolution.setToolTip("Auflösung der RDP-Sitzung für diese Maschine")
        for label, value in offered_resolutions():
            self.resolution.addItem(label, value)
        box.addWidget(self.resolution)
        self.all_monitors = QCheckBox("Alle Monitore")
        self.all_monitors.setObjectName("cardQuickCheck")
        self.all_monitors.setToolTip(
            "Die Sitzung über alle Bildschirme dieses PCs öffnen"
        )
        box.addWidget(self.all_monitors, 0, Qt.AlignRight)
        self._load_quick_settings(self.workstation)
        self.resolution.currentIndexChanged.connect(self._emit_display_settings)
        self.all_monitors.toggled.connect(self._emit_display_settings)
        return box

    def _load_quick_settings(self, workstation: Workstation) -> None:
        """Show the machine's stored choice without emitting a change."""
        for widget in (self.resolution, self.all_monitors):
            widget.blockSignals(True)
        try:
            stored = (workstation.resolution or "").replace(" ", "")
            windowed = (workstation.screen_mode or "").casefold() == "windowed"
            index = self.resolution.findData(stored) if (stored and windowed) else 0
            if index < 0:
                # Eine in den Details eingetragene Sondergroesse geht nicht
                # verloren, nur weil sie nicht in der kurzen Liste steht.
                self.resolution.addItem(stored, stored)
                index = self.resolution.count() - 1
            self.resolution.setCurrentIndex(index)
            self.all_monitors.setChecked(bool(workstation.use_all_monitors))
        finally:
            for widget in (self.resolution, self.all_monitors):
                widget.blockSignals(False)

    def _emit_display_settings(self) -> None:
        if self.workstation is None:
            return
        self.display_settings_changed.emit(
            self.workstation,
            self.resolution.currentData(),
            self.all_monitors.isChecked(),
        )

    @staticmethod
    def _site_text(workstation: Workstation) -> str:
        """Where the machine stands, shown directly under its name."""
        return workstation.site.strip() if (workstation.site or "").strip() else "Ohne Standort"

    @staticmethod
    def _description_text(workstation: Workstation) -> str:
        """Purpose and connection target -- the target moved here out of the title."""
        target = (
            workstation.hostname
            or workstation.fqdn
            or workstation.ip_address
            or "Kein Verbindungsziel"
        )
        return f"{workstation.description or 'Workstation'}  ·  {target}"

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.workstation)
        super().mousePressEvent(event)


class WorkstationCardsWidget(QWidget):
    """Responsive, searchable card grid for workstations."""

    workstation_selected = Signal(Workstation)
    connect_requested = Signal(Workstation)
    logoff_requested = Signal(Workstation)
    account_selected = Signal(Workstation, str)
    account_add_requested = Signal(Workstation)
    display_settings_changed = Signal(Workstation, object, bool)
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
            card.display_settings_changed.connect(self.display_settings_changed)
            items.append(card)
        for index, card in enumerate(items):
            row, column = divmod(index, columns)
            self.grid.addWidget(card, row, column)
            self._cards.append(card)
        # Die Karten haben eine feste Breite, also darf keine Spalte dehnen --
        # sonst reisst das Raster sie auseinander. Eine Reststrecke rechts
        # nimmt den uebrigen Platz auf, damit die Karten links stehen bleiben.
        for column in range(self.grid.columnCount()):
            self.grid.setColumnStretch(column, 0)
        self.grid.setColumnStretch(max(columns, self.grid.columnCount()), 1)
        self.scroll.verticalScrollBar().setValue(scroll_position)

    def _column_count(self) -> int:
        width = max(self.scroll.viewport().width(), self.width())
        # An der tatsaechlichen Kartenbreite ausgerichtet, sonst bleibt in
        # jeder Reihe eine Karte Platz ungenutzt oder eine zu viel gedraengt.
        return max(1, min(4, (width + CARD_GAP) // (CARD_WIDTH + CARD_GAP)))

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


__all__ = ["WorkstationCardsWidget", "WorkstationCard"]
