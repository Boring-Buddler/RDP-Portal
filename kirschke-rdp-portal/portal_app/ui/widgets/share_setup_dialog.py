"""Per-user Windows SMB connection setup with background connection checks."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from portal_app.services.share_connection import connect_share


class ShareConnectionWorker(QThread):
    result = Signal(str, str)
    failure = Signal(str)

    def __init__(self, path, username, password, remember, require_write=False, parent=None):
        super().__init__(parent)
        self.arguments = (path, username, password, remember, require_write)

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


def account_on_server(path: str, fallback: str) -> str:
    r"""Den Kontovorschlag an den Server im Pfad binden.

    ``PortalLeser`` ist ein *lokales* Konto auf jedem Zielrechner. Für
    ``\\NB05\RDP-Status`` meldet sich nur ``NB05\PortalLeser`` dort an, und ein
    Vorschlag wie ``NB13KI\PortalLeser`` daneben ist nicht bloß unschön, sondern
    schlicht falsch.

    Der Kontoname selbst wird aus dem Vorschlag übernommen: Wer sein Lesekonto
    anders genannt hat, soll das nicht bei jedem Pfadwechsel neu eintippen.
    """
    if not path.startswith("\\\\"):
        return fallback
    server = path[2:].split("\\", 1)[0].strip()
    if not server:
        return fallback
    _, _, account = fallback.rpartition("\\")
    return f"{server}\\{account or 'PortalLeser'}"


class ShareSetupDialog(QDialog):
    def __init__(
        self,
        current_path: str,
        parent=None,
        *,
        suggested_path: str = r"\\Remote-Ettlingen\RDP-Status",
        suggested_username: str = r"Remote-Ettlingen\PortalLeser",
        workstation_name: str = "",
        require_write: bool = False,
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
        # Fuer das gemeinsame Protokoll genuegt Leserecht nicht -- siehe
        # share_connection.verify_writable.
        self.require_write = require_write
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Der Ordner muss für das angegebene Konto beschreibbar sein. Das Portal "
            "prüft das vor dem Übernehmen, indem es eine Datei anlegt und wieder entfernt."
            if require_write
            else "Dieser Datei-Fallback gilt nur für die ausgewählte Maschine. "
            "Statusordner und Lesekonto müssen auf dem Zielrechner bereits eingerichtet sein."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        initial_path = current_path if current_path.startswith("\\\\") else suggested_path
        self.path = QLineEdit(initial_path)
        # Das Konto muss zu dem Server gehören, der im Pfad steht. Vorher kam
        # der Pfad aus dem gespeicherten Wert, der Vorschlag für das Konto aber
        # immer aus dem Namen der Maschine -- und dann standen hier Paare wie
        # \\NB05\RDP-Status mit NB13KI\PortalLeser, die nicht funktionieren
        # können: PortalLeser ist ein lokales Konto auf jedem Zielrechner, und
        # nur SERVER\PortalLeser meldet sich dort an.
        self._suggested_username = suggested_username
        self.username = QLineEdit(self._account_for(initial_path))
        self._username_edited = False
        self.username.textEdited.connect(self._remember_manual_username)
        self.path.textChanged.connect(self._follow_path)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Netzwerkordner", self.path)
        form.addRow("Freigabebenutzer", self.username)
        form.addRow("Kennwort", self.password)
        layout.addLayout(form)
        # Ein Statusordner auf einem anderen Rechner ist zulässig -- mehrere
        # Agenten dürfen in dieselbe Freigabe schreiben. Es ist aber auch die
        # Art von Eintrag, die aus einer früheren Einrichtung stehen bleibt,
        # und dann sucht das Portal den Status der Maschine an einem Ort, an
        # dem ihn niemand ablegt. Deshalb ein Hinweis und keine Sperre.
        self.server_note = QLabel()
        self.server_note.setWordWrap(True)
        self.server_note.setObjectName("cardMeta")
        layout.addWidget(self.server_note)
        # Beim gemeinsamen Protokoll gehoert der Ordner absichtlich nirgendwohin,
        # also gibt es auch nichts zu vergleichen.
        self._workstation_name = "" if require_write else workstation_name
        self._update_server_note(initial_path)
        self.path.textChanged.connect(self._update_server_note)
        self.remember = QCheckBox("Zugangsdaten für die Freigaben dieses Servers merken / ersetzen")
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        note = QLabel("Das Kennwort liegt in der Windows-Anmeldeinformationsverwaltung deines "
                      "Benutzerprofils, unter einem eigenen Eintrag des Portals. Das Portal "
                      "verbindet die Freigaben damit bei jedem Start selbst. Remotedesktop "
                      "nutzt diesen Eintrag nicht. Das Portal schreibt kein Kennwort in seine Dateien.")
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
        self.worker = ShareConnectionWorker(
            self.path.text(), self.username.text(), self.password.text(),
            self.remember.isChecked(), self.require_write, self,
        )
        self.password.clear()
        for widget in (self.path, self.username, self.password, self.remember, self.connect_button, self.cancel_button):
            widget.setEnabled(False)
        self.status.setText(
            "Windows verbindet die Freigabe und prüft den Schreibzugriff …"
            if self.require_write
            else "Windows verbindet die Freigabe und prüft den Lesezugriff …"
        )
        self.worker.result.connect(self._success)
        self.worker.failure.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _account_for(self, path: str) -> str:
        return account_on_server(path, self._suggested_username)

    def _update_server_note(self, path: str) -> None:
        """Sagen, wenn der Ordner auf einem anderen Rechner als der Maschine liegt."""
        server = path[2:].split("\\", 1)[0].strip() if path.startswith("\\\\") else ""
        machine = self._workstation_name.strip()
        if not server or not machine or server.casefold() == machine.casefold():
            self.server_note.setText("")
            return
        self.server_note.setText(
            f"Hinweis: Dieser Ordner liegt auf {server}, nicht auf {machine}. Das ist in "
            f"Ordnung, wenn der Agent von {machine} seinen Status dorthin schreibt — "
            "mehrere Agenten dürfen sich eine Freigabe teilen. Schreibt er ihn woanders "
            "hin, findet das Portal hier nichts."
        )

    def _remember_manual_username(self, _text: str) -> None:
        """Ab jetzt nicht mehr nachführen -- der Vorschlag wurde überschrieben."""
        self._username_edited = True

    def _follow_path(self, path: str) -> None:
        """Den Kontovorschlag dem Server im Pfad nachführen.

        Nur solange niemand das Konto selbst angefasst hat: Eine eingetippte
        Eingabe unter den Händen zu ändern wäre schlimmer als ein unpassender
        Vorschlag.
        """
        if not self._username_edited:
            self.username.setText(self._account_for(path))

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
