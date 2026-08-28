"""Editable general user and RDP login settings."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.user import MockUser


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

    def _accept(self) -> None:
        self.user.display_name = self.display_name.text().strip() or self.user.display_name
        self.user.upn = self.upn.text().strip() or self.user.upn
        self.user.email = self.email.text().strip() or None
        self.user.rdp_username = self.rdp_username.text().strip() or None
        self.user.rdp_domain = self.rdp_domain.text().strip() or None
        self.accept()


__all__ = ["UserSettingsDialog"]
