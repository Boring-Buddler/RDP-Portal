"""Editable general user and RDP login settings."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.user import MockUser
from shared.login_accounts import validate_login_account


class UserSettingsDialog(QDialog):
    def __init__(self, user: MockUser, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("Benutzer und Anmeldedaten")
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        title = QLabel("Allgemeine Anmeldedaten")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        note = QLabel(
            "Diese Angaben gelten standardmäßig für alle Maschinen. Ein Benutzername im "
            "Maschinenprofil hat Vorrang. Passwörter fragt Windows beim Verbindungsaufbau ab."
        )
        note.setObjectName("dialogNote")
        note.setWordWrap(True)
        root.addWidget(note)
        form = QFormLayout()
        form.setSpacing(12)
        self.display_name = QLineEdit(user.display_name)
        self.upn = QLineEdit(user.upn)
        self.email = QLineEdit(user.email or "")
        self.rdp_username = QLineEdit(user.rdp_username or "")
        self.rdp_domain = QLineEdit(user.rdp_domain or "")
        form.addRow("Anzeigename", self.display_name)
        form.addRow("UPN", self.upn)
        form.addRow("E-Mail", self.email)
        form.addRow("RDP-Benutzername", self.rdp_username)
        form.addRow("Domäne", self.rdp_domain)
        root.addLayout(form)

        own_title = QLabel("Weitere eigene Windows-Konten")
        own_title.setObjectName("dialogTitle")
        root.addWidget(own_title)
        own_note = QLabel(
            "Sitzungen dieser Konten gelten im Portal als deine eigenen, statt als "
            "fremde Belegung. Konten, mit denen du dich über das Portal verbindest, "
            "werden automatisch ergänzt.\n"
            "Das ändert nur die Anzeige: Windows fragt weiterhin das Kennwort ab, "
            "und der Agent prüft jede Abmeldung eigenständig."
        )
        own_note.setObjectName("dialogNote")
        own_note.setWordWrap(True)
        root.addWidget(own_note)
        self.own_accounts = QListWidget()
        self.own_accounts.setMinimumHeight(90)
        self.own_accounts.addItems(user.own_accounts)
        root.addWidget(self.own_accounts)
        own_row = QHBoxLayout()
        own_row.setSpacing(8)
        self.new_account = QLineEdit()
        self.new_account.setPlaceholderText("z. B. NB12KI\\Codex oder becker@prof-kirschke.de")
        self.new_account.returnPressed.connect(self._add_account)
        own_row.addWidget(self.new_account, 1)
        add_account = QPushButton("Hinzufügen")
        add_account.setObjectName("toolbarButton")
        add_account.clicked.connect(self._add_account)
        own_row.addWidget(add_account)
        remove_account = QPushButton("Entfernen")
        remove_account.setObjectName("toolbarButton")
        remove_account.clicked.connect(self._remove_account)
        own_row.addWidget(remove_account)
        root.addLayout(own_row)
        self.account_error = QLabel()
        self.account_error.setObjectName("dialogNote")
        self.account_error.setWordWrap(True)
        self.account_error.setVisible(False)
        root.addWidget(self.account_error)

        self.save_settings = QCheckBox("Einstellungen lokal speichern")
        self.save_settings.setChecked(True)
        root.addWidget(self.save_settings)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Übernehmen")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def should_save(self) -> bool:
        return self.save_settings.isChecked()

    def listed_accounts(self) -> list[str]:
        """The claimed accounts currently shown in the list."""
        return [
            self.own_accounts.item(row).text()
            for row in range(self.own_accounts.count())
        ]

    def _add_account(self) -> None:
        value = self.new_account.text().strip()
        if not value:
            return
        try:
            account = validate_login_account(value)
        except ValueError as exc:
            self.account_error.setText(str(exc))
            self.account_error.setVisible(True)
            return
        existing = {name.casefold() for name in self.listed_accounts()}
        if account.casefold() in existing:
            self.account_error.setText(f"{account} steht bereits in der Liste.")
            self.account_error.setVisible(True)
            return
        self.own_accounts.addItem(account)
        self.new_account.clear()
        self.account_error.setVisible(False)

    def _remove_account(self) -> None:
        for item in self.own_accounts.selectedItems():
            self.own_accounts.takeItem(self.own_accounts.row(item))
        self.account_error.setVisible(False)

    def _accept(self) -> None:
        self.user.display_name = self.display_name.text().strip() or self.user.display_name
        self.user.upn = self.upn.text().strip() or self.user.upn
        self.user.email = self.email.text().strip() or None
        self.user.rdp_username = self.rdp_username.text().strip() or None
        self.user.rdp_domain = self.rdp_domain.text().strip() or None
        self.user.own_accounts = self.listed_accounts()
        self.accept()


__all__ = ["UserSettingsDialog"]
