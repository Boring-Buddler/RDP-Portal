"""Functional administration and settings pages for the local test build."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QProcess, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.user import User
from portal_app.models.workstation import Workstation


class AdministrationWidget(QWidget):
    add_requested = Signal()
    edit_requested = Signal(Workstation)
    force_disconnect_requested = Signal(Workstation)
    delete_requested = Signal(Workstation)
    rdp_access_requested = Signal(Workstation)
    lock_requested = Signal()
    storage_directory_requested = Signal(str)
    active_directory_status_requested = Signal()

    def __init__(self, workstations: list[Workstation], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.workstations = workstations
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        actions = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("calendarRange")
        actions.addWidget(self.summary)
        self.access_status = QLabel("Admin-Sitzung gesperrt")
        self.access_status.setObjectName("adminAccessStatus")
        actions.addWidget(self.access_status)
        actions.addStretch()
        add = QPushButton("+ Maschine")
        add.setObjectName("cardPrimaryButton")
        add.clicked.connect(self.add_requested)
        actions.addWidget(add)
        edit = QPushButton("Auswahl bearbeiten")
        edit.setObjectName("toolbarButton")
        edit.clicked.connect(self._edit_selected)
        actions.addWidget(edit)
        self.rdp_access = QPushButton("RDP-Zugriff")
        self.rdp_access.setObjectName("toolbarButton")
        self.rdp_access.setEnabled(False)
        self.rdp_access.clicked.connect(self._manage_rdp_access_selected)
        actions.addWidget(self.rdp_access)
        self.force_disconnect = QPushButton("Trennen")
        self.force_disconnect.setObjectName("dangerButton")
        self.force_disconnect.setEnabled(False)
        self.force_disconnect.clicked.connect(self._force_disconnect_selected)
        actions.addWidget(self.force_disconnect)
        self.delete_workstation = QPushButton("Maschine löschen")
        self.delete_workstation.setObjectName("dangerButton")
        self.delete_workstation.setEnabled(False)
        self.delete_workstation.clicked.connect(self._delete_selected)
        actions.addWidget(self.delete_workstation)
        lock = QPushButton("Admin sperren")
        lock.setObjectName("toolbarButton")
        lock.clicked.connect(self.lock_requested)
        actions.addWidget(lock)
        root.addLayout(actions)
        storage_card = QFrame()
        storage_card.setObjectName("detailCard")
        storage_layout = QHBoxLayout(storage_card)
        storage_layout.setContentsMargins(16, 12, 16, 12)
        storage_layout.setSpacing(10)
        storage_copy = QVBoxLayout()
        storage_title = QLabel("SharePoint-Speicherort")
        storage_title.setObjectName("detailCardTitle")
        storage_copy.addWidget(storage_title)
        storage_note = QLabel(
            "Statusdatei und Ereignislog werden hier gespeichert. Beim Anwenden werden vorhandene Dateien verschoben."
        )
        storage_note.setObjectName("detailMuted")
        storage_note.setWordWrap(True)
        storage_copy.addWidget(storage_note)
        self.storage_status = QLabel("Gemeinsamer Speicher wird vorbereitet …")
        self.storage_status.setObjectName("detailMuted")
        self.storage_status.setWordWrap(True)
        storage_copy.addWidget(self.storage_status)
        storage_layout.addLayout(storage_copy)
        self.storage_directory = QLineEdit()
        self.storage_directory.setMinimumWidth(420)
        self.storage_directory.setPlaceholderText("Lokaler OneDrive-/SharePoint-Ordner")
        storage_layout.addWidget(self.storage_directory, 1)
        browse = QPushButton("Auswählen")
        browse.setObjectName("toolbarButton")
        browse.clicked.connect(self._choose_storage_directory)
        storage_layout.addWidget(browse)
        apply_storage = QPushButton("Dateien verschieben")
        apply_storage.setObjectName("toolbarButton")
        apply_storage.clicked.connect(self._apply_storage_directory)
        storage_layout.addWidget(apply_storage)
        root.addWidget(storage_card)
        directory_card = QFrame()
        directory_card.setObjectName("detailCard")
        directory_layout = QHBoxLayout(directory_card)
        directory_layout.setContentsMargins(16, 12, 16, 12)
        directory_layout.setSpacing(10)
        directory_copy = QVBoxLayout()
        directory_title = QLabel("Active Directory")
        directory_title.setObjectName("detailCardTitle")
        directory_copy.addWidget(directory_title)
        self.active_directory_status = QLabel("AD-Status wird beim Öffnen geprüft.")
        self.active_directory_status.setObjectName("detailMuted")
        self.active_directory_status.setWordWrap(True)
        directory_copy.addWidget(self.active_directory_status)
        directory_layout.addLayout(directory_copy, 1)
        refresh_directory_status = QPushButton("AD-Status prüfen")
        refresh_directory_status.setObjectName("toolbarButton")
        refresh_directory_status.clicked.connect(self.active_directory_status_requested)
        directory_layout.addWidget(refresh_directory_status)
        root.addWidget(directory_card)
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Name", "Hostname", "IP-Adresse", "Standort", "Status", "RDP-Zugriff"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda _: self._edit_selected())
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)
        self.refresh()

    def set_access_status(self, unlocked: bool, detail: str | None = None) -> None:
        self.access_status.setText(detail or ("Admin-Sitzung freigeschaltet" if unlocked else "Admin-Sitzung gesperrt"))
        self.access_status.setProperty("unlocked", unlocked)
        self.access_status.style().unpolish(self.access_status)
        self.access_status.style().polish(self.access_status)

    def set_workstations(self, workstations: list[Workstation]) -> None:
        self.workstations = workstations
        self.refresh()

    def set_storage_directory(self, directory: str) -> None:
        self.storage_directory.setText(directory)

    def set_storage_status(self, status: str) -> None:
        self.storage_status.setText(status)

    def set_active_directory_status(self, status: str) -> None:
        self.active_directory_status.setText(status)

    def _choose_storage_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "SharePoint-Speicherordner auswählen", self.storage_directory.text().strip()
        )
        if directory:
            self.storage_directory.setText(directory)

    def _apply_storage_directory(self) -> None:
        directory = self.storage_directory.text().strip()
        if directory:
            self.storage_directory_requested.emit(directory)

    def refresh(self) -> None:
        active = sum(ws.enabled for ws in self.workstations)
        self.summary.setText(f"{active} aktiv · {len(self.workstations)} Maschinen gesamt")
        self.table.setRowCount(len(self.workstations))
        for row, ws in enumerate(self.workstations):
            values = (ws.workstation_id, ws.display_name, ws.hostname, ws.ip_address or "–", ws.site or "–", ws.get_status_display())
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, ws.workstation_id)
                self.table.setItem(row, column, item)
        for row, ws in enumerate(self.workstations):
            item = QTableWidgetItem(f"{len(ws.rdp_access_users)} Nutzer")
            item.setData(Qt.UserRole, ws.workstation_id)
            self.table.setItem(row, 6, item)
        self.table.resizeColumnsToContents()

    def _edit_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.workstations):
            return
        self.edit_requested.emit(self.workstations[row])

    def _force_disconnect_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.workstations):
            return
        self.force_disconnect_requested.emit(self.workstations[row])

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.workstations):
            return
        self.delete_requested.emit(self.workstations[row])

    def _manage_rdp_access_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.workstations):
            return
        self.rdp_access_requested.emit(self.workstations[row])

    def _update_action_state(self) -> None:
        row = self.table.currentRow()
        enabled = 0 <= row < len(self.workstations)
        self.rdp_access.setEnabled(enabled)
        self.force_disconnect.setEnabled(enabled)
        self.delete_workstation.setEnabled(enabled)


class SettingsWidget(QWidget):
    edit_user_requested = Signal()
    agent_refresh_requested = Signal()
    theme_changed = Signal(str)

    def __init__(
        self,
        user: User,
        theme_mode: str = "system",
        dark_mode: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.user = user
        self.theme_mode = theme_mode
        self.dark_mode = dark_mode
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("settingsScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("settingsContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 10, 18)
        layout.setSpacing(16)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll)
        card = QFrame()
        card.setObjectName("detailCard")
        card.setMinimumHeight(176)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 20, 22, 20)
        card_layout.setSpacing(10)
        title = QLabel("Allgemeine RDP-Anmeldedaten")
        title.setObjectName("detailCardTitle")
        card_layout.addWidget(title)
        self.identity = QLabel()
        self.identity.setObjectName("detailValue")
        card_layout.addWidget(self.identity)
        self.rdp_login = QLabel()
        self.rdp_login.setObjectName("detailMuted")
        card_layout.addWidget(self.rdp_login)
        note = QLabel(
            "Diese Daten werden verwendet, wenn in einer Maschine kein eigener Benutzername hinterlegt ist. "
            "Windows fragt das Passwort beim Verbindungsaufbau ab."
        )
        note.setObjectName("detailMuted")
        note.setWordWrap(True)
        card_layout.addWidget(note)
        edit = QPushButton("Benutzerdaten bearbeiten")
        edit.setObjectName("toolbarButton")
        edit.clicked.connect(self.edit_user_requested)
        card_layout.addWidget(edit, alignment=Qt.AlignLeft)
        layout.addWidget(card)
        theme_card = QFrame()
        theme_card.setObjectName("detailCard")
        theme_card.setMinimumHeight(142)
        theme_layout = QVBoxLayout(theme_card)
        theme_layout.setContentsMargins(22, 20, 22, 20)
        theme_layout.setSpacing(7)
        theme_title = QLabel("Darstellung")
        theme_title.setObjectName("detailCardTitle")
        theme_layout.addWidget(theme_title)
        theme_note = QLabel("Hoher Kontrast für längeres Arbeiten und schlecht lesbare Umgebungen.")
        theme_note.setObjectName("detailMuted")
        theme_note.setText("Standard: Windows-Systemeinstellung. Mit dem Button wechseln Sie die Darstellung.")
        theme_note.setWordWrap(True)
        theme_layout.addWidget(theme_note)
        self.theme_toggle_button = QPushButton()
        self.theme_toggle_button.setObjectName("toolbarButton")
        self.theme_toggle_button.clicked.connect(self._toggle_theme)
        theme_layout.addWidget(self.theme_toggle_button, alignment=Qt.AlignLeft)
        self._update_theme_toggle_button()
        layout.addWidget(theme_card)
        network_card = QFrame()
        network_card.setObjectName("detailCard")
        network_card.setMinimumHeight(360)
        network_layout = QVBoxLayout(network_card)
        network_layout.setContentsMargins(22, 20, 22, 20)
        network_layout.setSpacing(10)
        network_header = QHBoxLayout()
        network_copy = QVBoxLayout()
        network_copy.setSpacing(3)
        network_title = QLabel("Eigene Netzwerkinformationen")
        network_title.setObjectName("detailCardTitle")
        network_copy.addWidget(network_title)
        self.network_status = QLabel("ipconfig /all wird geladen …")
        self.network_status.setObjectName("detailMuted")
        network_copy.addWidget(self.network_status)
        network_header.addLayout(network_copy, 1)
        self.copy_network_btn = QPushButton("Kopieren")
        self.copy_network_btn.setObjectName("toolbarButton")
        self.copy_network_btn.setEnabled(False)
        self.copy_network_btn.clicked.connect(self._copy_network_info)
        network_header.addWidget(self.copy_network_btn)
        self.refresh_network_btn = QPushButton("Aktualisieren")
        self.refresh_network_btn.setObjectName("toolbarButton")
        self.refresh_network_btn.clicked.connect(self.load_network_info)
        network_header.addWidget(self.refresh_network_btn)
        network_layout.addLayout(network_header)
        self.network_output = QPlainTextEdit()
        self.network_output.setObjectName("networkOutput")
        self.network_output.setReadOnly(True)
        self.network_output.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.network_output.setMaximumHeight(270)
        self.network_output.setPlaceholderText("Die Ausgabe von ipconfig /all erscheint hier.")
        network_layout.addWidget(self.network_output)
        layout.addWidget(network_card)

        self.ipconfig_process: QProcess | None = None
        agent_card = QFrame()
        agent_card.setObjectName("detailCard")
        agent_card.setMinimumHeight(192)
        agent_layout = QVBoxLayout(agent_card)
        agent_layout.setContentsMargins(22, 20, 22, 20)
        agent_layout.setSpacing(10)
        agent_title = QLabel("Windows-Agent · lokaler Testkanal")
        agent_title.setObjectName("detailCardTitle")
        agent_layout.addWidget(agent_title)
        self.agent_status = QLabel("Noch nicht geprüft")
        self.agent_status.setObjectName("detailValue")
        agent_layout.addWidget(self.agent_status)
        self.agent_path = QLabel()
        self.agent_path.setObjectName("detailMuted")
        self.agent_path.setWordWrap(True)
        agent_layout.addWidget(self.agent_path)
        agent_note = QLabel(
            "Der Agent veröffentlicht hier seinen echten lokalen WTS-Sitzungsstatus. "
            "In der Produktivphase übernimmt Microsoft Graph diesen Transport zwischen den Rechnern."
        )
        agent_note.setObjectName("detailMuted")
        agent_note.setWordWrap(True)
        agent_layout.addWidget(agent_note)
        refresh_agent = QPushButton("Agentstatus jetzt einlesen")
        refresh_agent.setObjectName("toolbarButton")
        refresh_agent.clicked.connect(self.agent_refresh_requested)
        agent_layout.addWidget(refresh_agent, alignment=Qt.AlignLeft)
        layout.addWidget(agent_card)
        layout.addStretch()
        self.refresh()
        self.network_load_timer = QTimer(self)
        self.network_load_timer.setSingleShot(True)
        self.network_load_timer.timeout.connect(self.load_network_info)
        self.network_load_timer.start(0)

    def set_user(self, user: User) -> None:
        self.user = user
        self.refresh()

    def set_theme_mode(self, theme_mode: str, dark_mode: bool) -> None:
        self.theme_mode = theme_mode
        self.dark_mode = dark_mode
        self._update_theme_toggle_button()

    def _update_theme_toggle_button(self) -> None:
        self.theme_toggle_button.setText(
            "Zum Hellmodus wechseln" if self.dark_mode else "Zum Dunkelmodus wechseln"
        )

    @Slot()
    def _toggle_theme(self) -> None:
        self.theme_changed.emit("light" if self.dark_mode else "dark")

    def refresh(self) -> None:
        self.identity.setText(f"{self.user.display_name} · {self.user.upn}")
        self.rdp_login.setText(f"RDP: {self.user.get_rdp_username() or 'Beim Start abfragen'}")


    @Slot()
    def load_network_info(self) -> None:
        if self.ipconfig_process is not None:
            return
        self.network_status.setText("ipconfig /all wird ausgeführt …")
        self.network_output.clear()
        self.refresh_network_btn.setEnabled(False)
        self.copy_network_btn.setEnabled(False)
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.finished.connect(self._on_ipconfig_finished)
        process.errorOccurred.connect(self._on_ipconfig_error)
        self.ipconfig_process = process
        process.start("ipconfig", ["/all"])

    @Slot(int, QProcess.ExitStatus)
    def _on_ipconfig_finished(
        self,
        exit_code: int,
        exit_status: QProcess.ExitStatus,
    ) -> None:
        if self.ipconfig_process is None:
            return
        output = self._decode_console_output(bytes(self.ipconfig_process.readAll()))
        success = exit_code == 0 and exit_status == QProcess.NormalExit and bool(output.strip())
        self.network_output.setPlainText(output.strip())
        self.network_status.setText(
            "Lokale Netzwerkinformationen · aktuell"
            if success
            else f"ipconfig wurde mit Code {exit_code} beendet"
        )
        self.copy_network_btn.setEnabled(bool(output.strip()))
        self.refresh_network_btn.setEnabled(True)
        self.ipconfig_process.deleteLater()
        self.ipconfig_process = None

    @Slot(QProcess.ProcessError)
    def _on_ipconfig_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.FailedToStart or self.ipconfig_process is None:
            return
        self.network_status.setText("ipconfig konnte nicht gestartet werden")
        self.network_output.setPlainText("Das Windows-Programm ipconfig wurde nicht gefunden.")
        self.refresh_network_btn.setEnabled(True)
        self.ipconfig_process.deleteLater()
        self.ipconfig_process = None

    @staticmethod
    def _decode_console_output(data: bytes) -> str:
        encodings = ["utf-8"]
        if sys.platform == "win32":
            encodings.insert(0, f"cp{ctypes.windll.kernel32.GetOEMCP()}")
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode(errors="replace")

    @Slot()
    def _copy_network_info(self) -> None:
        QApplication.clipboard().setText(self.network_output.toPlainText())

    def set_agent_bridge_status(self, matched: int, snapshots: int, path: str) -> None:
        if snapshots == 0:
            self.agent_status.setText("Kein lokaler Agentstatus gefunden")
        else:
            self.agent_status.setText(
                f"{matched} Maschine(n) aktualisiert · {snapshots} Statusdatei(en)"
            )
        self.agent_path.setText(f"Statusordner: {path}")


__all__ = ["AdministrationWidget", "SettingsWidget"]
