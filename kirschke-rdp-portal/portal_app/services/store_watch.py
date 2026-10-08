"""Prüft im Hintergrund, ob sich das gemeinsame Inventar geändert hat.

Liegt das Inventar auf einer Netzwerkfreigabe, kann schon das ``stat`` einer
Datei so lange hängen, wie der SMB-Client auf den Server wartet. Der Abgleich
läuft alle paar Sekunden; im UI-Thread hätte jede Störung der Freigabe das
Fenster eingefroren. Hier werden nur die Signaturen ermittelt -- verglichen und
nachgeladen wird im UI-Thread.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from portal_app.services.local_store import file_signatures


class _ProbeSignals(QObject):
    finished = Signal(object, object)


class _ProbeTask(QRunnable):
    def __init__(self, paths: tuple[Path, ...]) -> None:
        super().__init__()
        self.paths = paths
        self.signals = _ProbeSignals()

    @Slot()
    def run(self) -> None:
        self.signals.finished.emit(self.paths, file_signatures(self.paths))


class StoreChangeProbe(QObject):
    """Eine Messung zur Zeit; eine laufende wird nicht doppelt gestartet."""

    completed = Signal(object, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._task: _ProbeTask | None = None
        self._stopped = False

    @property
    def busy(self) -> bool:
        return self._task is not None

    def request(self, paths: tuple[Path, ...]) -> bool:
        if self._stopped or self._task is not None:
            return False
        task = _ProbeTask(tuple(paths))
        task.signals.finished.connect(self._on_finished)
        self._task = task
        self.pool.start(task)
        return True

    @Slot(object, object)
    def _on_finished(self, paths: object, signatures: object) -> None:
        self._task = None
        if not self._stopped:
            self.completed.emit(paths, signatures)

    def stop(self) -> None:
        self._stopped = True
        self.pool.clear()


__all__ = ["StoreChangeProbe"]
