"""Wait until a console session has become an RDP session of this machine.

Taking a console session over is what makes it endable at all: the agent refuses
a logoff it cannot attribute, and a session at the device itself has no RDP client
for Windows to attest.  Once the same account connects from here, the session
carries this machine as its client and the ordinary check accepts it.

This dialog only watches for that transition.  It changes nothing, and giving up
costs nothing beyond the connection the user just opened.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from portal_app.models.workstation import Workstation
from shared.session_identity import is_active_session, is_console_session
from shared.status_pipe import request_snapshot

logger = logging.getLogger(__name__)

#: How long to wait for the takeover before giving up.  Generous, because Windows
#: asks for credentials in between and a person has to type them.
TIMEOUT_SECONDS = 150

#: How often to ask the agent.  A live query costs a few milliseconds, so this can
#: stay on the UI thread without making the dialog feel stuck.
INTERVAL_MS = 2000


class SessionTakeoverDialog(QDialog):
    """Poll the agent until one of ``accounts`` owns a non-console session."""

    def __init__(
        self,
        workstation: Workstation,
        accounts,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.workstation = workstation
        self.accounts = list(accounts)
        self.remaining = TIMEOUT_SECONDS
        self.setWindowTitle("Sitzung übernehmen")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        self.status = QLabel(
            f"Warte darauf, dass {workstation.display_name} die Sitzung als Sitzung "
            "dieses Rechners meldet.\n\nMelde dich im RDP-Fenster an, falls Windows "
            "danach fragt. Danach wird die Sitzung abgemeldet."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.cancel = QPushButton("Abbrechen")
        self.cancel.setObjectName("toolbarButton")
        self.cancel.clicked.connect(self.reject)
        layout.addWidget(self.cancel)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check)
        self.timer.start(INTERVAL_MS)

    def _check(self) -> None:
        self.remaining -= INTERVAL_MS / 1000
        if self.remaining <= 0:
            self.timer.stop()
            self.status.setText(
                "Die Sitzung wurde in der Wartezeit nicht als Sitzung dieses Rechners "
                "gemeldet. Prüfe das RDP-Fenster und versuche es erneut, oder nimm die "
                "administrative Abmeldung."
            )
            self.cancel.setText("Schließen")
            return
        if self._taken_over():
            self.timer.stop()
            self.accept()

    def _taken_over(self) -> bool:
        """Whether the agent now reports an own, non-console session."""
        try:
            snapshot, _elapsed = request_snapshot(self.workstation.get_agent_status_target())
        except Exception:
            # A single failed query means nothing here; the next tick tries again.
            logger.debug("Übernahme-Prüfung: Agent antwortete nicht", exc_info=True)
            return False
        from shared.identity import WindowsIdentity

        for session in snapshot.rdp_sessions:
            if not is_active_session(session) or is_console_session(session):
                continue
            identity = WindowsIdentity.from_session(session)
            if any(account.matches(identity) for account in self.accounts):
                return True
        return False

    def reject(self) -> None:
        self.timer.stop()
        super().reject()


__all__ = ["SessionTakeoverDialog", "TIMEOUT_SECONDS"]
