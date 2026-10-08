"""One place in the settings for agents, their machines and the file fallback.

Before this, the three things that decide whether a machine reports anything at
all lived in three different corners: the shared reader account nowhere at all
(it was re-typed into a dialog per machine), the agent assignment behind
Maschinen → Details → „Agent zuordnen …", and the fallback share behind another
button on the same detail page.  Somebody setting up a new office had to walk
that path once per machine and had no way to see what was already working.

The panel shows the whole mapping as a table and puts the two actions that apply
to *all* machines -- store the reader account, reconnect every share -- above it.
It owns no data: every change leaves as a signal and comes back as a refreshed
machine list, because the inventory and the store belong to MainWindow.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.workstation import Workstation
from portal_app.ui.design import scaled
from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox as QComboBox
from portal_app.ui.widgets.table_cells import reset_rows

#: Combo entry meaning "match by machine ID or host name", the default.
AUTOMATIC = "__auto__"

_SOURCE_LABELS = {
    "live": "Live-Kanal",
    "file": "Datei-Fallback",
    "none": "keine Meldung",
}


class AgentConnectionPanel(QFrame):
    """Central agent, machine-mapping and fallback administration."""

    wizard_requested = Signal()
    reconnect_requested = Signal()
    credentials_save_requested = Signal(str, str)
    agent_assignment_changed = Signal(str, str)
    fallback_setup_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("detailCard")
        self.workstations: list[Workstation] = []
        self._known_agent_ids: list[str] = []
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        title = QLabel("Agenten, Zuordnung und Datei-Fallback")
        title.setObjectName("detailCardTitle")
        layout.addWidget(title)
        intro = QLabel(
            "Der Verbindungsassistent sucht Agenten im Netzwerk, legt fehlende Maschinen an "
            "und richtet deren Datei-Fallback ein. Ein einmal hinterlegtes Lesekonto verbindet "
            "die Statusfreigaben danach bei jedem Start automatisch."
        )
        intro.setObjectName("detailMuted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        actions = QHBoxLayout()
        self.wizard_button = QPushButton("Verbindungsassistent öffnen …")
        self.wizard_button.setObjectName("cardPrimaryButton")
        self.wizard_button.clicked.connect(self.wizard_requested)
        actions.addWidget(self.wizard_button)
        self.reconnect_button = QPushButton("Alle Fallbacks jetzt verbinden")
        self.reconnect_button.setObjectName("toolbarButton")
        self.reconnect_button.clicked.connect(self.reconnect_requested)
        actions.addWidget(self.reconnect_button)
        actions.addStretch()
        layout.addLayout(actions)

        credentials = QHBoxLayout()
        reader_label = QLabel("Gemeinsames Lesekonto")
        # Without the object name the card's stylesheet leaves it unreadable.
        reader_label.setObjectName("detailLabel")
        credentials.addWidget(reader_label)
        self.reader_user = QLineEdit()
        self.reader_user.setPlaceholderText("PortalLeser")
        credentials.addWidget(self.reader_user, 1)
        self.reader_password = QLineEdit()
        self.reader_password.setEchoMode(QLineEdit.Password)
        self.reader_password.setPlaceholderText("Kennwort")
        self.reader_password.returnPressed.connect(self._save_credentials)
        credentials.addWidget(self.reader_password, 1)
        self.save_credentials_button = QPushButton("Speichern und verbinden")
        self.save_credentials_button.setObjectName("toolbarButton")
        self.save_credentials_button.clicked.connect(self._save_credentials)
        credentials.addWidget(self.save_credentials_button)
        layout.addLayout(credentials)
        self.credentials_status = QLabel()
        self.credentials_status.setObjectName("detailMuted")
        self.credentials_status.setWordWrap(True)
        layout.addWidget(self.credentials_status)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Maschine", "Agent-Zuordnung", "Quelle", "Datei-Fallback", ""]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(220)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        # Textzellen kürzt die Tabelle selbst mit „…“; Auswahlfeld und Knopf
        # nicht. Ihre Spalten und die Zeilenhöhe folgen deshalb dem Inhalt --
        # mit festen Maßen fehlte bei größerer Schrift ihr Text.
        for column, width in ((0, 230), (2, 130)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, scaled(width))
        for column in (1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setMinimumSectionSize(scaled(36))
        layout.addWidget(self.table, 1)
        self.summary = QLabel()
        self.summary.setObjectName("detailMuted")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

    def set_reader_account(self, username: str, source: str = "stored") -> None:
        """Show which reader account is in use and where it comes from.

        The source matters to whoever reads this line: a bundled account needs no
        action, a stored one was somebody's correction on this PC, and neither
        means the same thing as having none.
        """
        self.reader_user.setText(username)
        self.credentials_status.setText(
            {
                "bundled": f"Mitgeliefert mit dieser Portalversion: {username}. Ein Eintrag hier "
                "gilt nur auf diesem PC und hat Vorrang.",
                "stored": f"Auf diesem PC hinterlegt: {username}. Das Kennwort liegt in der "
                "Windows-Anmeldeinformationsverwaltung, nicht in einer Portaldatei.",
            }.get(
                source if username else "none",
                "Noch kein Lesekonto. Ohne Konto verbindet Windows die Freigaben nur, wenn "
                "dafür bereits Zugangsdaten gespeichert sind.",
            )
        )

    def set_status(self, message: str) -> None:
        self.credentials_status.setText(message)

    def set_known_agents(self, agent_ids: list[str]) -> None:
        """Offer agents a sweep found, even before any machine claims them."""
        self._known_agent_ids = sorted({value.strip() for value in agent_ids if value.strip()})
        self.set_workstations(self.workstations)

    def set_workstations(self, workstations: list[Workstation]) -> None:
        self.workstations = workstations
        self._loading = True
        try:
            reset_rows(self.table, len(workstations))
            for row, ws in enumerate(workstations):
                self._fill_row(row, ws)
        finally:
            self._loading = False
        reporting = sum(ws.agent_status_source in ("live", "file") for ws in workstations)
        explicit = sum(ws.agent_fallback_is_explicit for ws in workstations)
        self.summary.setText(
            f"{reporting} von {len(workstations)} Maschinen melden Status · "
            f"{explicit} mit eigenem Datei-Fallback"
        )

    def _fill_row(self, row: int, ws: Workstation) -> None:
        name = QTableWidgetItem(f"{ws.display_name} · {ws.workstation_id}")
        name.setData(Qt.UserRole, ws.workstation_id)
        self.table.setItem(row, 0, name)

        combo = QComboBox()
        combo.addItem("Automatisch (ID / Hostname)", AUTOMATIC)
        candidates = list(self._known_agent_ids)
        current = (ws.agent_workstation_id or "").strip()
        if current and current not in candidates:
            candidates.append(current)
        for agent_id in candidates:
            combo.addItem(agent_id, agent_id)
        index = combo.findData(current) if current else 0
        combo.setCurrentIndex(max(0, index))
        combo.setProperty("workstationId", ws.workstation_id)
        combo.currentIndexChanged.connect(self._on_assignment_changed)
        self.table.setCellWidget(row, 1, combo)

        source = QTableWidgetItem(_SOURCE_LABELS.get(ws.agent_status_source, ws.agent_status_source))
        source.setToolTip(ws.agent_diagnostic)
        self.table.setItem(row, 2, source)

        path = (
            ws.agent_fallback_directory or "–"
            if ws.agent_fallback_is_explicit
            else "nicht eingerichtet"
        )
        fallback = QTableWidgetItem(path)
        fallback.setToolTip(path)
        self.table.setItem(row, 3, fallback)

        button = QPushButton("Fallback …")
        button.setObjectName("toolbarButton")
        button.setProperty("workstationId", ws.workstation_id)
        button.clicked.connect(self._on_fallback_clicked)
        self.table.setCellWidget(row, 4, button)

    @Slot()
    def _save_credentials(self) -> None:
        username = self.reader_user.text().strip()
        password = self.reader_password.text()
        self.reader_password.clear()
        if not username or not password:
            self.credentials_status.setText("Benutzername und Kennwort des Lesekontos eingeben.")
            return
        self.credentials_save_requested.emit(username, password)

    @Slot()
    def _on_assignment_changed(self) -> None:
        if self._loading:
            return
        combo = self.sender()
        if combo is None:
            return
        workstation_id = str(combo.property("workstationId") or "")
        value = combo.currentData()
        if workstation_id:
            self.agent_assignment_changed.emit(
                workstation_id, "" if value == AUTOMATIC else str(value)
            )

    @Slot()
    def _on_fallback_clicked(self) -> None:
        button = self.sender()
        if button is None:
            return
        workstation_id = str(button.property("workstationId") or "")
        if workstation_id:
            self.fallback_setup_requested.emit(workstation_id)


__all__ = ["AUTOMATIC", "AgentConnectionPanel"]
