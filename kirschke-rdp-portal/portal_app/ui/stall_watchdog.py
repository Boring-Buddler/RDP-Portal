"""Hält im Log fest, wann und wo der UI-Thread hängt.

Ein hängendes Fenster lässt sich am Arbeitsplatz kaum nachstellen: Es hängt an
einer langsamen Freigabe, einer Maschine ohne Netz oder einem DNS ohne Antwort.
Dieses Modul macht solche Hänger im ``portal.log`` sichtbar, samt der Stelle im
Code, an der der UI-Thread gerade steht.

Aufbau: Ein Qt-Timer im UI-Thread setzt alle ``HEARTBEAT_MS`` einen
Zeitstempel. Ein eigener Thread prüft ihn. Bleibt der Takt länger als
``STALL_THRESHOLD_SECONDS`` aus, steht die Ereignisschleife -- der Wachhund
schreibt dann den aktuellen Stack des UI-Threads ins Log und, sobald der Takt
wiederkommt, wie lange es insgesamt gedauert hat.

Das kostet einen Python-Aufruf alle 50 ms im UI-Thread. Jeden Slot einzeln zu
messen hätte dagegen jedes Qt-Ereignis durch Python geführt und das Portal
selbst langsamer gemacht.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

logger = logging.getLogger(__name__)

#: Ab dieser Dauer ohne Takt gilt der UI-Thread als hängend.
STALL_THRESHOLD_SECONDS = 0.2

#: Abstand des Takts im UI-Thread und der Prüfung im Wachhund-Thread.
HEARTBEAT_MS = 50

#: So viele Stack-Ebenen reichen, um vom Slot bis zum hängenden Aufruf zu sehen.
STACK_LIMIT = 15


class UiStallWatchdog(QObject):
    """Protokolliert Hänger des UI-Threads mit Stack und Gesamtdauer."""

    def __init__(
        self,
        threshold_seconds: float = STALL_THRESHOLD_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.threshold_seconds = threshold_seconds
        self._ui_thread_id = threading.get_ident()
        # Nur der UI-Thread schreibt, nur der Wachhund liest. Eine einzelne
        # Zuweisung eines float ist dafür ausreichend atomar.
        self._last_beat = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(HEARTBEAT_MS)
        self._timer.timeout.connect(self._beat)
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Im UI-Thread aufrufen, sobald die Ereignisschleife läuft."""
        if self._thread is not None:
            return
        self._ui_thread_id = threading.get_ident()
        self._last_beat = time.monotonic()
        self._timer.start()
        self._thread = threading.Thread(
            target=self._watch, daemon=True, name="portal-ui-watchdog"
        )
        self._thread.start()
        logger.info(
            "UI-Wachhund aktiv: Hänger ab %d ms werden protokolliert.",
            self.threshold_seconds * 1000,
        )

    def stop(self) -> None:
        self._stopped.set()
        self._timer.stop()

    def _beat(self) -> None:
        self._last_beat = time.monotonic()

    def _watch(self) -> None:
        # Der Takt, bei dem der laufende Hänger begann; None, solange alles läuft.
        stalled_since: float | None = None
        while not self._stopped.wait(HEARTBEAT_MS / 1000):
            beat = self._last_beat
            if stalled_since is not None and beat != stalled_since:
                logger.warning(
                    "UI-Thread war %d ms blockiert.",
                    (beat - stalled_since) * 1000,
                )
                stalled_since = None
            lag = time.monotonic() - beat
            if stalled_since is None and lag >= self.threshold_seconds:
                stalled_since = beat
                logger.warning(
                    "UI-Thread reagiert seit %d ms nicht. Aktuelle Stelle:\n%s",
                    lag * 1000,
                    self._ui_stack(),
                )

    def _ui_stack(self) -> str:
        frame = sys._current_frames().get(self._ui_thread_id)
        if frame is None:
            return "(Stack nicht verfügbar)"
        return "".join(traceback.format_stack(frame, limit=STACK_LIMIT)).rstrip()


__all__ = ["STALL_THRESHOLD_SECONDS", "UiStallWatchdog"]
