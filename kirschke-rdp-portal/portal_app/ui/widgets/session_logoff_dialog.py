"""Explicit confirmation and background native signout."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from portal_app.services.session_control import logoff_own_session


class LogoffWorker(QThread):
    result = Signal(str)

    def __init__(self, arguments, parent=None):
        super().__init__(parent)
        self.arguments = arguments

    def run(self):
        try:
            logoff_own_session(*self.arguments)
            self.result.emit("Windows hat die Abmeldung angefordert. Die Anzeige wird aktualisiert, "
                             "sobald der Agent das Ende der Sitzung meldet.")
        except ValueError as exc:
            self.result.emit(str(exc))
        except Exception as exc:
            code = getattr(exc, "winerror", None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            self.result.emit(f"Windows-Abmeldung nicht möglich (Fehler {code or type(exc).__name__}). "
                             "Der direkte Zugriff auf die Windows-Sitzungsverwaltung benötigt eigene "
                             "Windows-Berechtigungen und Netzwerkzugriff; der lesbare Statusordner genügt nicht. "
                             "Du kannst dich erneut verbinden und auf dem Zielrechner Start → Benutzer → Abmelden wählen.")


class SessionLogoffDialog(QDialog):
    def __init__(self, target, machine_name, session, parent=None):
        super().__init__(parent)
        self.worker = None
        self.setWindowTitle("Vom Zielrechner abmelden")
        self.setMinimumWidth(520)
        username = session.get("full_username") or ((session.get("domain") + "\\") if session.get("domain") else "") + (session.get("username") or "")
        self.arguments = (target, session["session_id"], username, session["login_time"])
        layout = QVBoxLayout(self)
        self.status = QLabel(f"{machine_name} · {username} · Sitzung {session['session_id']}\n\n"
                             "Abmelden beendet die Programme dieser Sitzung. Nicht gespeicherte Arbeit kann verloren gehen.\n\n"
                             "Windows prüft, ob diese Sitzung deinem aktuellen Windows-Konto gehört. "
                             "Die Auswahl eines Kontonamens im Portal erteilt keine Berechtigung.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.confirm = QPushButton("Sitzung jetzt abmelden")
        self.confirm.setObjectName("toolbarButton")
        self.confirm.setAutoDefault(False)
        self.confirm.clicked.connect(self._start)
        layout.addWidget(self.confirm)
        self.cancel = QPushButton("Schließen")
        self.cancel.setObjectName("toolbarButton")
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)

    def _start(self):
        self.confirm.setEnabled(False)
        self.cancel.setEnabled(False)
        self.status.setText("Windows prüft die Sitzung und fordert die Abmeldung an …")
        self.worker = LogoffWorker(self.arguments, self)
        self.worker.result.connect(self.status.setText)
        self.worker.finished.connect(lambda: self.cancel.setEnabled(True))
        self.worker.start()

    def reject(self):
        if self.worker is None or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
