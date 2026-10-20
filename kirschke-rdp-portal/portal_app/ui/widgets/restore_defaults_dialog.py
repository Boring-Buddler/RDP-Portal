"""Bestätigung für "Standard wiederherstellen", zugleich die Admin-Abfrage.

Die Maschinenliste zu ersetzen ist eine Admin-Aufgabe, die Statusfreigaben mit
dem Lesekonto einzurichten nicht. Statt einer Admin-Abfrage, an der alles
scheitert, bietet der Dialog deshalb an, ohne Admin den Teil zu erledigen, der
ohne Admin geht.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class RestoreDefaultsDialog(QDialog):
    """Erklärt beide Teile und fragt das Admin-Passwort ab.

    ``verify`` prüft ein eingegebenes Passwort und gibt eine Fehlermeldung
    zurück, leer bei Erfolg. ``admin_needed`` ist falsch, wenn es nichts gibt,
    wofür der Admin-Zugang nötig wäre -- etwa beim gemeinsamen Inventar.
    """

    def __init__(
        self,
        admin_part: str,
        basic_part: str,
        *,
        admin_needed: bool,
        admin_open: bool,
        password_allowed: bool,
        verify: Callable[[str], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.verify = verify
        self.with_admin = False
        self._admin_open = admin_open or not admin_needed
        self.setWindowTitle("Standard wiederherstellen")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        title = QLabel("Standard wiederherstellen")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        for heading, text in (("Mit Admin-Zugang", admin_part), ("Immer, auch ohne Admin", basic_part)):
            label = QLabel(f"<b>{heading}</b><br>{text}" if admin_needed else text)
            label.setObjectName("dialogNote")
            label.setWordWrap(True)
            root.addWidget(label)
            if not admin_needed:
                break
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Globales Portal-Admin-Passwort")
        self.password.setAccessibleName("Admin-Passwort")
        # Enter löst den Standardknopf aus; ein zweiter Weg über returnPressed
        # zählte jeden Fehlversuch doppelt gegen die Sperre.
        self.password.setVisible(not self._admin_open)
        self.password.setEnabled(password_allowed)
        root.addWidget(self.password)
        self.message = QLabel()
        self.message.setObjectName("dialogNote")
        self.message.setWordWrap(True)
        if admin_needed and admin_open:
            self.message.setText("Der Admin-Zugang ist bereits offen.")
        elif admin_needed and not password_allowed:
            self.message.setText(
                "Die Passwort-Freigabe ist im AD-Modus deaktiviert; ohne Admin-Gruppe "
                "bleibt nur der Teil ohne Admin."
            )
        self.message.setVisible(bool(self.message.text()))
        root.addWidget(self.message)

        buttons = QDialogButtonBox()
        self.admin_button = QPushButton(
            "Mit Admin wiederherstellen" if admin_needed else "Wiederherstellen"
        )
        self.admin_button.setDefault(True)
        self.admin_button.setEnabled(self._admin_open or password_allowed)
        buttons.addButton(self.admin_button, QDialogButtonBox.AcceptRole)
        self.admin_button.clicked.connect(self._restore_with_admin)
        self.skip_button = QPushButton("Ohne Admin fortfahren")
        self.skip_button.setToolTip(
            "Überspringt die Admin-Abfrage und richtet nur die Statusfreigaben ein; "
            "die Maschinenliste bleibt unverändert."
        )
        self.skip_button.setVisible(admin_needed and not admin_open)
        buttons.addButton(self.skip_button, QDialogButtonBox.ActionRole)
        self.skip_button.clicked.connect(self._restore_without_admin)
        cancel = buttons.addButton(QDialogButtonBox.Cancel)
        cancel.setText("Abbrechen")
        cancel.clicked.connect(self.reject)
        root.addWidget(buttons)
        if self.password.isVisible() and password_allowed:
            self.password.setFocus()

    def _restore_with_admin(self) -> None:
        if not self._admin_open:
            if not self.password.text():
                self._show_error("Bitte das Admin-Passwort eingeben oder ohne Admin fortfahren.")
                return
            error = self.verify(self.password.text())
            if error:
                self.password.clear()
                self._show_error(error)
                return
        self.with_admin = True
        self.accept()

    def _restore_without_admin(self) -> None:
        self.with_admin = False
        self.accept()

    def _show_error(self, text: str) -> None:
        self.message.setText(text)
        self.message.setVisible(True)
        self.password.setFocus()


__all__ = ["RestoreDefaultsDialog"]
