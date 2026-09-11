"""Per-user Windows SMB connection setup with background connection checks."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QCheckBox, QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from portal_app.services.share_connection import connect_share


class ShareConnectionWorker(QThread):
    result = Signal(str, str)
    failure = Signal(str)

    def __init__(self, path, username, password, remember, parent=None):
        super().__init__(parent)
        self.arguments = (path, username, password, remember)

    def run(self):
        try:
            self.result.emit(*connect_share(*self.arguments))
        except ValueError as exc:
            self.failure.emit(str(exc))
        except Exception as exc:
            # Do not expose exception arguments: some APIs can include secrets.
            self.failure.emit(f"Einrichtung fehlgeschlagen ({type(exc).__name__}). "
                              "Bitte diese Fehlerklasse zusammen mit der Portalversion melden.")
        finally:
            self.arguments = None


class ShareSetupDialog(QDialog):
    def __init__(
        self,
        current_path: str,
        parent=None,
        *,
        suggested_path: str = r"\\Remote-Ettlingen\RDP-Status",
        suggested_username: str = r"Remote-Ettlingen\PortalLeser",
        workstation_name: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(
            f"Fallback für {workstation_name} einrichten"
            if workstation_name
            else "Netzwerkfreigabe einrichten"
        )
        self.setMinimumWidth(560)
        self.worker = None
        self.connected_path = ""
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Dieser Datei-Fallback gilt nur für die ausgewählte Maschine. "
            "Statusordner und Lesekonto müssen auf dem Zielrechner bereits eingerichtet sein."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.path = QLineEdit(current_path if current_path.startswith("\\\\") else suggested_path)
        self.username = QLineEdit(suggested_username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Netzwerkordner", self.path)
        form.addRow("Freigabebenutzer", self.username)
        form.addRow("Kennwort", self.password)
        layout.addLayout(form)
        self.remember = QCheckBox("Zugangsdaten in Windows für diesen Server speichern / ersetzen")
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        note = QLabel("Windows speichert das Kennwort für dein Benutzerprofil auf diesem PC. "
                      "Es gilt auch für andere Dateifreigaben desselben Servers. "
                      "Die RDP-Anmeldung bleibt separat. Das Portal schreibt kein Kennwort in seine Dateien.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.connect_button = QPushButton("Verbinden, prüfen und übernehmen")
        self.connect_button.setObjectName("toolbarButton")
        self.connect_button.clicked.connect(self._connect)
        layout.addWidget(self.connect_button)
        self.cancel_button = QPushButton("Schließen")
        self.cancel_button.setObjectName("toolbarButton")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

    def _connect(self):
        self.connected_path = ""
        self.worker = ShareConnectionWorker(self.path.text(), self.username.text(), self.password.text(), self.remember.isChecked(), self)
        self.password.clear()
        for widget in (self.path, self.username, self.password, self.remember, self.connect_button, self.cancel_button):
            widget.setEnabled(False)
        self.status.setText("Windows verbindet die Freigabe und prüft den Lesezugriff …")
        self.worker.result.connect(self._success)
        self.worker.failure.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _success(self, path, message):
        self.connected_path = path
        self.status.setText(message)

    def _finished(self):
        for widget in (self.path, self.username, self.password, self.remember, self.connect_button, self.cancel_button):
            widget.setEnabled(True)
        if self.connected_path:
            self.accept()

    def reject(self):
        if self.worker is None or not self.worker.isRunning():
            self.password.clear()
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
        else:
            self.password.clear()
            super().closeEvent(event)
