"""Bounded background polling for the agent's read-only live status channel."""

from __future__ import annotations

import time
from collections.abc import Iterable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from portal_app.models.workstation import Workstation
from shared.status_pipe import request_snapshot


class _LiveStatusSignals(QObject):
    succeeded = Signal(str, object, object, int)
    failed = Signal(str, object, str)
    completed = Signal(str)


class _LiveStatusTask(QRunnable):
    def __init__(self, workstation_id: str, target: str, route: object) -> None:
        super().__init__()
        self.workstation_id = workstation_id
        self.target = target
        self.route = route
        self.signals = _LiveStatusSignals()

    @Slot()
    def run(self) -> None:
        try:
            snapshot, elapsed = request_snapshot(self.target)
        except Exception as exc:
            code = getattr(exc, "winerror", None)
            if code is None and exc.args and isinstance(exc.args[0], int):
                code = exc.args[0]
            label = str(code or type(exc).__name__)
            self.signals.failed.emit(
                self.workstation_id,
                self.route,
                f"Live-Abfrage fehlgeschlagen ({label}).",
            )
        else:
            self.signals.succeeded.emit(
                self.workstation_id,
                self.route,
                snapshot,
                elapsed,
            )
        finally:
            self.signals.completed.emit(self.target.casefold())


class AutomaticLiveStatusPoller(QObject):
    """Run independent status requests with per-target overlap protection/backoff."""

    succeeded = Signal(str, object, object, int)
    failed = Signal(str, object, str)

    def __init__(self, max_parallel: int = 4, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, max_parallel))
        self._in_flight: set[str] = set()
        self._tasks: dict[str, _LiveStatusTask] = {}
        self._failure_counts: dict[str, int] = {}
        self._retry_after: dict[str, float] = {}
        self._stopped = False
        # Plain attribute on purpose: a private property whose getter read an
        # unmangled "__current_interval" string silently pinned this to 5, so
        # set_interval() never reached the backoff calculation.
        self.interval_seconds = 5

    def request_many(
        self,
        workstations: Iterable[Workstation],
        interval_seconds: int,
        *,
        force: bool = False,
    ) -> int:
        """Queue eligible machines and return how many new requests were started."""
        if self._stopped:
            return 0
        self.set_interval(interval_seconds)
        started = 0
        now = time.monotonic()
        for workstation in workstations:
            if not workstation.enabled:
                continue
            try:
                target = workstation.get_agent_status_target()
            except ValueError as exc:
                self.failed.emit(workstation.workstation_id, None, str(exc))
                continue
            route = target
            key = target.casefold()
            if key in self._in_flight:
                continue
            if not force and now < self._retry_after.get(key, 0.0):
                continue
            task = _LiveStatusTask(workstation.workstation_id, target, route)
            task.signals.succeeded.connect(self._on_succeeded)
            task.signals.failed.connect(self._on_failed)
            task.signals.completed.connect(self._on_completed)
            self._in_flight.add(key)
            self._tasks[key] = task
            self.pool.start(task)
            started += 1
        return started

    @Slot(str, object, object, int)
    def _on_succeeded(
        self,
        workstation_id: str,
        route: object,
        snapshot: object,
        elapsed: int,
    ) -> None:
        key = str(route).casefold()
        self._failure_counts.pop(key, None)
        self._retry_after.pop(key, None)
        if not self._stopped:
            self.succeeded.emit(workstation_id, route, snapshot, elapsed)

    @Slot(str, object, str)
    def _on_failed(self, workstation_id: str, route: object, message: str) -> None:
        key = str(route).casefold() if route else workstation_id.casefold()
        failures = self._failure_counts.get(key, 0) + 1
        self._failure_counts[key] = failures
        # Failed machines are retried progressively less often, while healthy
        # targets remain independent in the bounded worker pool.
        delay = min(60, self.interval_seconds * (2 ** min(failures - 1, 3)))
        self._retry_after[key] = time.monotonic() + delay
        if not self._stopped:
            self.failed.emit(workstation_id, route, message)

    @Slot(str)
    def _on_completed(self, key: str) -> None:
        self._in_flight.discard(key)
        self._tasks.pop(key, None)

    def set_interval(self, seconds: int) -> None:
        """Store the configured poll interval that drives the failure backoff."""
        self.interval_seconds = max(2, min(60, int(seconds)))

    def stop(self) -> None:
        self._stopped = True
        self.pool.clear()


__all__ = ["AutomaticLiveStatusPoller"]
