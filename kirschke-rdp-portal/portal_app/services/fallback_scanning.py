"""Off-thread reading of the agent status folders (finding ST1).

The file fallback reads UNC paths.  An unreachable SMB host blocks for the SMB
timeout, so the read must not happen in the Qt main thread -- it used to, while
the calling docstring claimed otherwise.  Only the read moves here; applying the
result to Workstation objects stays on the UI thread.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from portal_app.services.agent_status import DirectoryScan, LocalAgentStatusService


class _ScanSignals(QObject):
    finished = Signal(object)


class _ScanTask(QRunnable):
    def __init__(self, directories: dict[str, Path]) -> None:
        super().__init__()
        self.directories = directories
        self.signals = _ScanSignals()

    @Slot()
    def run(self) -> None:
        try:
            scans = LocalAgentStatusService.scan_directories(self.directories)
        except Exception as exc:  # noqa: BLE001 - reported as a per-folder read error
            scans = {
                key: DirectoryScan(
                    directory, [], [], [f"{directory}: Ordner kann nicht gelesen werden: {exc}"]
                )
                for key, directory in self.directories.items()
            }
        self.signals.finished.emit(scans)


class FallbackScanner(QObject):
    """Run one folder scan at a time in the background.

    Overlapping scans are dropped rather than queued: the next timer tick reads
    the folders again anyway, so a slow share must not build up a backlog.
    """

    completed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._busy = False
        self._stopped = False
        self._task: _ScanTask | None = None

    @property
    def busy(self) -> bool:
        return self._busy

    def request(self, directories: dict[str, Path]) -> bool:
        """Start a scan. Returns False when one is already running or stopped."""
        if self._stopped or self._busy or not directories:
            return False
        self._busy = True
        task = _ScanTask(dict(directories))
        task.signals.finished.connect(self._on_finished)
        self._task = task
        self.pool.start(task)
        return True

    @Slot(object)
    def _on_finished(self, scans: object) -> None:
        self._busy = False
        self._task = None
        if not self._stopped:
            self.completed.emit(scans)

    def stop(self) -> None:
        self._stopped = True
        self.pool.clear()
        self.pool.waitForDone(3000)


__all__ = ["FallbackScanner"]
