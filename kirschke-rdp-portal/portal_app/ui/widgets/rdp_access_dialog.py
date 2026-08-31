"""Administrative editor for per-workstation RDP group membership."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.workstation import Workstation


class RDPAccessDialog(QDialog):
    """Choose known directory accounts or add one account manually."""

    def __init__(
        self,
        workstation: Workstation,
        directory_accounts: list[str],
        directory_message: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstation = workstation
        self.directory_accounts = self._normalise(directory_accounts + workstation.rdp_access_users)
        self.members = self._normalise(workstation.rdp_access_users)
        self.sync_to_active_directory = False
        self.setObjectName("rdpAccessDialog")
        self.setWindowTitle("RDP-Zugriff verwalten")
        self.setMinimumSize(760, 570)
        self.resize(820, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(14)
        title = QLabel(f"RDP-Zugriff · {workstation.display_name}")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        group_name = QLabel(f"Zielgruppe: RDP-{workstation.workstation_id}")
        group_name.setObjectName("calendarRange")
        root.addWidget(group_name)
        note = QLabel(
            "Mitglieder werden im gemeinsamen Portalstand gespeichert und protokolliert. "
            "Mit ‚In AD übernehmen‘ wird die Windows-Domänengruppe gezielt mit dem aktuellen Windows-Konto abgeglichen."
        )
        note.setObjectName("detailMuted")
        note.setWordWrap(True)
        root.addWidget(note)

        chooser = QFrame()
        chooser.setObjectName("detailCard")
        chooser_layout = QVBoxLayout(chooser)
        chooser_layout.setContentsMargins(16, 14, 16, 14)
        chooser_layout.setSpacing(8)
        chooser_title = QLabel("Benutzerverzeichnis")
        chooser_title.setObjectName("detailCardTitle")
        chooser_layout.addWidget(chooser_title)
        self.directory_status = QLabel(directory_message)
        self.directory_status.setObjectName("detailMuted")
        self.directory_status.setWordWrap(True)
        chooser_layout.addWidget(self.directory_status)
        self.search = QLineEdit()
        self.search.setObjectName("rdpAccessSearch")
        self.search.setPlaceholderText("Benutzer suchen, z. B. becker oder KIRSCHKE\\becker")
        self.search.textChanged.connect(self._refresh_directory)
        chooser_layout.addWidget(self.search)
        self.directory_list = QListWidget()
        self.directory_list.setMinimumHeight(115)
        self.directory_list.itemDoubleClicked.connect(lambda _: self._add_selected())
        chooser_layout.addWidget(self.directory_list)
        add_selected = QPushButton("Auswahl hinzufügen")
        add_selected.setObjectName("toolbarButton")
        add_selected.clicked.connect(self._add_selected)
        chooser_layout.addWidget(add_selected, alignment=Qt.AlignRight)
        root.addWidget(chooser)

        manual = QHBoxLayout()
        self.manual_account = QLineEdit()
        self.manual_account.setPlaceholderText("Manuell: KIRSCHKE\\becker oder becker@firma.de")
        self.manual_account.returnPressed.connect(self._add_manual)
        manual.addWidget(self.manual_account, 1)
        add_manual = QPushButton("Manuell hinzufügen")
        add_manual.setObjectName("toolbarButton")
        add_manual.clicked.connect(self._add_manual)
        manual.addWidget(add_manual)
        root.addLayout(manual)

        member_title = QLabel("Mitglieder dieser RDP-Gruppe")
        member_title.setObjectName("detailCardTitle")
        root.addWidget(member_title)
        self.member_table = QTableWidget(0, 1)
        self.member_table.setHorizontalHeaderLabels(["Benutzerkonto"])
        self.member_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.member_table.setSelectionMode(QTableWidget.SingleSelection)
        self.member_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.member_table.horizontalHeader().setStretchLastSection(True)
        self.member_table.setMinimumHeight(125)
        root.addWidget(self.member_table, 1)
        footer = QHBoxLayout()
        remove = QPushButton("Ausgewählten entfernen")
        remove.setObjectName("dangerButton")
        remove.clicked.connect(self._remove_selected)
        footer.addWidget(remove)
        footer.addStretch()
        cancel = QPushButton("Abbrechen")
        cancel.setObjectName("toolbarButton")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        save = QPushButton("Nur speichern")
        save.setObjectName("toolbarButton")
        save.clicked.connect(self.accept)
        footer.addWidget(save)
        sync = QPushButton("In AD übernehmen")
        sync.setObjectName("cardPrimaryButton")
        sync.clicked.connect(self._accept_for_active_directory)
        footer.addWidget(sync)
        root.addLayout(footer)
        self._refresh_directory()
        self._refresh_members()

    @staticmethod
    def _normalise(accounts: list[str]) -> list[str]:
        unique: dict[str, str] = {}
        for account in accounts:
            cleaned = str(account or "").strip()
            if cleaned:
                unique.setdefault(cleaned.casefold(), cleaned)
        return sorted(unique.values(), key=str.casefold)

    @property
    def selected_members(self) -> list[str]:
        return list(self.members)

    @property
    def known_accounts(self) -> list[str]:
        return list(self.directory_accounts)

    def _refresh_directory(self) -> None:
        search = self.search.text().strip().casefold()
        self.directory_list.clear()
        for account in self.directory_accounts:
            if not search or search in account.casefold():
                item = QListWidgetItem(account)
                item.setData(Qt.UserRole, account)
                self.directory_list.addItem(item)

    def _refresh_members(self) -> None:
        self.member_table.setRowCount(len(self.members))
        for row, account in enumerate(self.members):
            item = QTableWidgetItem(account)
            item.setData(Qt.UserRole, account)
            self.member_table.setItem(row, 0, item)

    def _add_selected(self) -> None:
        item = self.directory_list.currentItem()
        if item is None:
            return
        self._add_account(str(item.data(Qt.UserRole) or item.text()))

    def _add_manual(self) -> None:
        account = self.manual_account.text().strip()
        if not account:
            return
        if " " in account or ("\\" not in account and "@" not in account):
            QMessageBox.warning(
                self,
                "Benutzerkonto prüfen",
                "Bitte ein Konto im Format DOMÄNE\\benutzer oder benutzer@firma.de eingeben.",
            )
            return
        self._add_account(account)
        self.manual_account.clear()

    def _add_account(self, account: str) -> None:
        if account.casefold() not in {member.casefold() for member in self.members}:
            self.members = self._normalise(self.members + [account])
            self._refresh_members()
        self.directory_accounts = self._normalise(self.directory_accounts + [account])
        self._refresh_directory()

    def _remove_selected(self) -> None:
        row = self.member_table.currentRow()
        if row < 0 or row >= len(self.members):
            return
        self.members.pop(row)
        self._refresh_members()

    def _accept_for_active_directory(self) -> None:
        self.sync_to_active_directory = True
        self.accept()


__all__ = ["RDPAccessDialog"]
