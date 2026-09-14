"""Explicit confirmation and background native signout."""
import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from portal_app.services.session_control import logoff_admin_session, logoff_own_session
from shared.session_identity import session_username

logger = logging.getLogger(__name__)


class LogoffWorker(QThread):
    result = Signal(bool, str)

    def __init__(self, arguments, administrative=False, credentials=None, parent=None,
                 hostnames=None):
        super().__init__(parent)
        self.arguments = arguments
        self.administrative = administrative
        self.credentials = credentials
        self.hostnames = hostnames

    def run(self):
        try:
            operation = logoff_admin_session if self.administrative else logoff_own_session
            if self.administrative:
                operation(*self.arguments, admin_credentials=self.credentials,
                          hostnames=self.hostnames)
            else:
                operation(*self.arguments, hostnames=self.hostnames)
            self.result.emit(True, "Windows hat die Sitzung abgemeldet. Der Agent hat das Sitzungsende "
                             "frisch bestätigt; die Anzeige wird aktualisiert.")
        except (ValueError, RuntimeError, PermissionError) as exc:
            self.result.emit(False, str(exc))
        except Exception as exc:
            # Everything the portal itself refuses carries its own reason above.
            # Reaching this point means a Windows call failed, so name which one:
            # the old text described a direct remote session call the portal no
            # longer makes, which made "Fehler 5" unexplainable.
            logger.exception("Abmeldung fehlgeschlagen")
            code = getattr(exc, "winerror", None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            detail = f"{type(exc).__name__}: {exc}".strip()
            hint = ""
            if code == 5:
                hint = (
                    "\n\nFehler 5 ist „Zugriff verweigert“. Die Abmeldung läuft über den "
                    "Agent-Kanal des Zielrechners; das Portal-Konto braucht dort Zugriff "
                    "auf die Named Pipe (Lesekonto PortalLeser). Prüfe, ob der Agent läuft "
                    "und ob dieser Portal-PC am Zielrechner angemeldet ist."
                )
            self.result.emit(
                False,
                f"Die Abmeldung wurde von Windows abgebrochen (Fehler {code or type(exc).__name__})."
                f"{hint}\n\nDetails: {detail}\n\n"
                "Alternativ kannst du dich verbinden und auf dem Zielrechner "
                "Start → Benutzer → Abmelden wählen.",
            )


class SessionLogoffDialog(QDialog):
    request_finished = Signal(bool, str)

    def __init__(
        self,
        target,
        machine_name,
        session,
        parent=None,
        *,
        administrative=False,
        expected_agent_id=None,
        status_target=None,
        hostnames=None,
    ):
        super().__init__(parent)
        self.worker = None
        self.administrative = administrative
        self.setWindowTitle("Vom Zielrechner abmelden")
        self.setMinimumWidth(520)
        username = session_username(session)
        self.arguments = (
            target,
            session["session_id"],
            username,
            session["login_time"],
            expected_agent_id,
            status_target,
        )
        # Zusaetzliche Hinweise darauf, dass der antwortende Agent zu dieser
        # Maschine gehoert -- None heisst: die Zuordnung wurde von Hand gesetzt.
        self.hostnames = hostnames
        layout = QVBoxLayout(self)
        security_note = (
            "Windows prüft die unten eingegebenen administrativen Zugangsdaten direkt am Zielrechner. "
            "PortalLeser und die Portal-Adminfreischaltung allein erteilen keine Abmeldeberechtigung."
            if administrative
            else "Windows prüft, ob diese Sitzung deinem aktuellen Windows-Konto gehört. "
            "Die Auswahl eines Kontonamens im Portal erteilt keine Berechtigung."
        )
        self.status = QLabel(f"{machine_name} · {username} · Sitzung {session['session_id']}\n\n"
                             "Abmelden beendet laufende Programme. Ungespeicherte Arbeit kann verloren gehen.\n\n"
                             f"{security_note}")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.admin_username = None
        self.admin_password = None
        if administrative:
            admin_label = QLabel("Windows-Administratorkonto auf dem Zielrechner")
            layout.addWidget(admin_label)
            self.admin_username = QLineEdit()
            server = (status_target or machine_name).split(".", 1)[0]
            self.admin_username.setPlaceholderText(fr"{server}\Administrator")
            layout.addWidget(self.admin_username)
            password_label = QLabel("Kennwort (wird nicht gespeichert)")
            layout.addWidget(password_label)
            self.admin_password = QLineEdit()
            self.admin_password.setEchoMode(QLineEdit.Password)
            layout.addWidget(self.admin_password)
        self.confirm = QPushButton(
            "Fremde Sitzung administrativ abmelden" if administrative else "Sitzung jetzt abmelden"
        )
        self.confirm.setObjectName("dangerButton")
        self.confirm.setAutoDefault(False)
        self.confirm.clicked.connect(self._start)
        layout.addWidget(self.confirm)
        self.cancel = QPushButton("Schließen")
        self.cancel.setObjectName("toolbarButton")
        self.cancel.setDefault(True)
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)

    def _start(self):
        credentials = None
        if self.administrative:
            username = self.admin_username.text().strip()
            password = self.admin_password.text()
            if not username or not password:
                self.status.setText(
                    "Für die administrative Abmeldung werden echte Windows-Administrator-Anmeldedaten "
                    "des Zielrechners benötigt."
                )
                return
            credentials = (username, password)
            self.admin_password.clear()
        self.confirm.setEnabled(False)
        self.cancel.setEnabled(False)
        self.status.setText("Windows prüft die Sitzung und fordert die Abmeldung an …")
        self.worker = LogoffWorker(self.arguments, self.administrative, credentials, self,
                                   hostnames=self.hostnames)
        self.worker.result.connect(self._finished_request)
        self.worker.finished.connect(lambda: self.cancel.setEnabled(True))
        self.worker.start()

    def _finished_request(self, success: bool, message: str) -> None:
        self.status.setText(message)
        self.request_finished.emit(success, message)

    def reject(self):
        if self.worker is None or not self.worker.isRunning():
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
