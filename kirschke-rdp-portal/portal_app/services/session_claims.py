"""Dem Agenten melden, wer sich gerade aufgeschaltet hat.

Zwei Dinge hängen daran, und das zweite bestimmt den Aufbau dieses Moduls.

**Wer davor sitzt.** Auf eine Workstation verbindet sich bewusst jeder unter
demselben gemeinsamen Windows-Konto. Der Kontoname sagt damit nichts darüber
aus, wer die Maschine hält; ohne Meldung erkennt jedes Portal das gemeinsame
Konto als das eigene wieder und zeigt die Maschine allen als "von dir belegt".

**Ob überhaupt über das Portal verbunden wurde.** Weil *jede* vom Portal
gestartete Verbindung gemeldet wird, ist das Ausbleiben einer Meldung selbst
eine Auskunft: Diese Sitzung kam vermutlich nicht über das Portal, sondern etwa
direkt über ``mstsc``. Wer sie hält, ist dann nur über den Kontonamen
erschlossen.

Genau deshalb reicht ein einzelner Versuch nicht. Wäre eine Meldung schon
verloren, weil der Agent im falschen Moment nicht erreichbar war, hieße das
hinterher fälschlich "nicht über das Portal verbunden". Eine ausgebliebene
Meldung muss etwas bedeuten, also wird sie wiederholt, solange die Sitzung
besteht -- siehe :class:`SessionClaimReporter`.

Was das nicht ist: ein Nachweis. Siehe :mod:`workstation_agent.claim_store` für
die Vertrauensgrenze und für die Regel, die daraus folgt.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from shared.session_identity import is_active_session, session_username
from shared.status_pipe import push_session_claim

logger = logging.getLogger(__name__)

#: Wie lange eine unbestätigte Meldung wiederholt wird, wenn die Maschine keine
#: passende Sitzung meldet. Deckt eine Anmeldung ab, die noch an einer
#: Kennwort- oder Entra-Abfrage hängt; danach ist die Verbindung offenbar nie
#: zustande gekommen und es gibt nichts mehr zu melden.
UNCONFIRMED_MAX_AGE_SECONDS = 900


def build_claim(user: User, account: str) -> dict:
    """Die Meldung selbst: Welcher Mensch verbindet sich unter welchem Konto.

    ``owner_display`` ist das, was auf den Karten der Kollegen steht, deshalb
    lieber ein Anzeigename als eine UPN. Verglichen wird trotzdem immer über
    ``owner_upn``, weil ein Anzeigename nicht eindeutig sein muss.
    """
    return {
        "account": account.strip(),
        "owner_upn": user.upn.strip(),
        "owner_display": (user.display_name or user.upn).strip(),
        "claimed_at_utc": datetime.now(UTC).isoformat(),
    }


@dataclass
class PendingClaim:
    """Eine Meldung, die noch nicht beim Agenten angekommen ist."""

    workstation_id: str
    account: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attempts: int = 0
    last_error: str = ""
    #: time.monotonic() des letzten Versuchs, für den Mindestabstand.
    last_attempt_at: float = 0.0


class SessionClaimReporter:
    """Hält offene Aufschaltmeldungen fest, bis der Agent sie hat.

    Eine Meldung gilt als erledigt, sobald der Agent sie bestätigt -- oder
    sobald er sie im Snapshot zurückmeldet, was dasselbe beweist und auch dann
    greift, wenn die Bestätigung unterwegs verloren ging.

    Aufgegeben wird nur, wenn es nichts mehr zu melden gibt: Die Maschine führt
    keine Sitzung unter diesem Konto und die Meldung ist älter als
    :data:`UNCONFIRMED_MAX_AGE_SECONDS`.
    """

    #: Mindestabstand zwischen zwei Wiederholungen derselben Meldung in
    #: :meth:`flush`. Null heisst: bei jedem Aufruf versuchen.
    retry_spacing_seconds = 0.0

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], PendingClaim] = {}

    @staticmethod
    def _key(workstation_id: str, account: str) -> tuple[str, str]:
        return workstation_id, account.strip().casefold()

    @property
    def pending(self) -> list[PendingClaim]:
        """Die offenen Meldungen, für Diagnose und Tests."""
        return list(self._pending.values())

    def report(self, workstation: Workstation, user: User, account: str | None) -> str:
        """Eine gestartete Verbindung melden und bei Misserfolg vormerken.

        Gibt eine leere Zeichenkette zurück, wenn die Meldung angekommen ist,
        sonst einen kurzen Grund fürs Protokoll. Wirft nie: Eine misslungene
        Meldung ist ein Anzeigeproblem, keine misslungene Verbindung -- die
        läuft zu diesem Zeitpunkt bereits.
        """
        account = (account or "").strip()
        if not account or not user.upn.strip():
            return "Kein Kontoname oder keine Benutzerkennung für die Aufschaltmeldung."
        key = self._key(workstation.workstation_id, account)
        entry = self._pending.get(key) or PendingClaim(workstation.workstation_id, account)
        self._pending[key] = entry
        return self._attempt(workstation, user, entry)

    def _prepare(
        self, workstation: Workstation, user: User, entry: PendingClaim
    ) -> tuple[str, dict] | str:
        """Ziel und Meldung festlegen. Gibt bei fehlendem Ziel den Grund zurück.

        Liest das Workstation-Objekt und gehört deshalb in den UI-Thread.
        """
        entry.attempts += 1
        entry.last_attempt_at = time.monotonic()
        try:
            target = workstation.get_agent_status_target()
        except ValueError as exc:
            entry.last_error = str(exc)
            return f"Kein Agentenziel für {workstation.display_name}: {exc}"
        return target, build_claim(user, entry.account)

    def _record(self, display_name: str, entry: PendingClaim, error: str) -> None:
        """Ergebnis eines Zustellversuchs festhalten."""
        if not error:
            self._pending.pop(self._key(entry.workstation_id, entry.account), None)
            return
        entry.last_error = error
        logger.info(
            "Aufschaltung für %s (Versuch %d) nicht zugestellt: %s",
            display_name,
            entry.attempts,
            error,
        )

    def _attempt(self, workstation: Workstation, user: User, entry: PendingClaim) -> str:
        prepared = self._prepare(workstation, user, entry)
        if isinstance(prepared, str):
            return prepared
        target, claim = prepared
        try:
            push_session_claim(target, claim)
        except Exception as exc:  # noqa: BLE001 - jede Pipe-Störung ist hier gleichwertig
            self._record(workstation.display_name, entry, str(exc))
            return str(exc)
        self._record(workstation.display_name, entry, "")
        return ""

    def flush(self, workstations: list[Workstation], user: User) -> int:
        """Offene Meldungen erneut versuchen. Gibt zurück, wie viele noch offen sind.

        Läuft im Statustakt mit. Vorher wird aufgeräumt, was der Agent bereits
        hat oder was nie mehr ankommen wird, damit keine Meldung endlos gegen
        eine abgeschaltete Maschine läuft.
        """
        if not self._pending:
            return 0
        machines = {item.workstation_id: item for item in workstations}
        now = datetime.now(UTC)
        monotonic_now = time.monotonic()
        for key, entry in list(self._pending.items()):
            workstation = machines.get(entry.workstation_id)
            if workstation is None:
                # Die Maschine gibt es im Portal nicht mehr.
                del self._pending[key]
                continue
            if self._already_known(workstation, entry, user):
                del self._pending[key]
                continue
            if self._is_futile(workstation, entry, now):
                logger.info(
                    "Aufschaltung für %s aufgegeben: keine Sitzung unter %s. Letzter Fehler: %s",
                    workstation.display_name,
                    entry.account,
                    entry.last_error or "keiner",
                )
                del self._pending[key]
                continue
            if (
                entry.attempts
                and monotonic_now - entry.last_attempt_at < self.retry_spacing_seconds
            ):
                continue
            self._attempt(workstation, user, entry)
        return len(self._pending)

    @staticmethod
    def _already_known(workstation: Workstation, entry: PendingClaim, user: User) -> bool:
        """Ob der Agent genau diese Meldung bereits zurückmeldet.

        Das ist der bessere Beweis als die Bestätigung des Schreibvorgangs: Er
        gilt auch dann, wenn die Antwort des Agenten unterwegs verloren ging.
        """
        account = entry.account.strip().casefold()
        for claim in workstation.agent_session_claims or []:
            if not isinstance(claim, dict):
                continue
            same_account = str(claim.get("account") or "").strip().casefold() == account
            same_person = (
                str(claim.get("owner_upn") or "").strip().casefold()
                == user.upn.strip().casefold()
            )
            if same_account and same_person:
                return True
        return False

    @staticmethod
    def _is_futile(workstation: Workstation, entry: PendingClaim, now: datetime) -> bool:
        """Ob es nichts mehr zu melden gibt.

        Solange die Maschine eine Sitzung unter diesem Konto führt, wird weiter
        versucht, egal wie lange -- dort sitzt jemand, und genau das soll ja
        sichtbar werden. Erst ohne Sitzung läuft die Frist.
        """
        account = entry.account.strip().casefold()
        for item in workstation.reported_sessions():
            if is_active_session(item) and session_username(item).strip().casefold() == account:
                return False
        return (now - entry.created_at).total_seconds() > UNCONFIRMED_MAX_AGE_SECONDS


class _ClaimSignals(QObject):
    finished = Signal(object, str)


class _ClaimTask(QRunnable):
    """Eine Meldung über die Pipe zustellen. Kennt nur Ziel und Meldung."""

    def __init__(self, key: tuple[str, str], target: str, claim: dict) -> None:
        super().__init__()
        self.key = key
        self.target = target
        self.claim = claim
        self.signals = _ClaimSignals()

    @Slot()
    def run(self) -> None:
        try:
            push_session_claim(self.target, self.claim)
        except Exception as exc:  # noqa: BLE001 - jede Pipe-Störung ist hier gleichwertig
            self.signals.finished.emit(self.key, str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit(self.key, "")


class _ClaimDelivery(QObject):
    """Führt die Pipe-Aufrufe aus und meldet das Ergebnis im UI-Thread zurück."""

    delivered = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        # Eine Meldung nach der anderen: Es sind wenige, und eine gegen eine
        # abgeschaltete Maschine soll nicht mehrere Threads binden.
        self.pool.setMaxThreadCount(1)
        self._tasks: dict[tuple[str, str], _ClaimTask] = {}
        self.stopped = False

    def start(self, key: tuple[str, str], target: str, claim: dict) -> None:
        task = _ClaimTask(key, target, claim)
        task.signals.finished.connect(self._on_finished)
        self._tasks[key] = task
        self.pool.start(task)

    @Slot(object, str)
    def _on_finished(self, key: tuple[str, str], error: str) -> None:
        self._tasks.pop(key, None)
        if not self.stopped:
            self.delivered.emit(key, error)

    def stop(self) -> None:
        self.stopped = True
        self.pool.clear()


class BackgroundSessionClaimReporter(SessionClaimReporter):
    """Wie :class:`SessionClaimReporter`, aber die Pipe läuft im Hintergrund.

    Die Zustellung wartet auf ``WaitNamedPipe``, auf den SMB-Verbindungsaufbau
    und auf die Antwort des Agenten -- gegen eine abgeschaltete Maschine
    mehrere Sekunden. Im UI-Thread hing damit bei jedem Statuslauf das
    Fenster. Hier bleibt nur die Buchführung im UI-Thread; der Pipe-Aufruf
    selbst geht in einen eigenen Thread, und das Ergebnis kommt per Signal
    zurück.

    :meth:`report` gibt deshalb auch dann eine leere Zeichenkette zurück, wenn
    die Meldung nur übergeben wurde. Ein Fehlschlag wird bei Eintreffen
    protokolliert und im nächsten Statuslauf wiederholt.
    """

    retry_spacing_seconds = 5.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__()
        self._in_flight: set[tuple[str, str]] = set()
        self._display_names: dict[tuple[str, str], str] = {}
        self._delivery = _ClaimDelivery(parent)
        self._delivery.delivered.connect(self._on_delivered)

    def _attempt(self, workstation: Workstation, user: User, entry: PendingClaim) -> str:
        key = self._key(entry.workstation_id, entry.account)
        if key in self._in_flight or self._delivery.stopped:
            return ""
        prepared = self._prepare(workstation, user, entry)
        if isinstance(prepared, str):
            return prepared
        target, claim = prepared
        self._in_flight.add(key)
        self._display_names[key] = workstation.display_name
        self._delivery.start(key, target, claim)
        return ""

    def _on_delivered(self, key: tuple[str, str], error: str) -> None:
        self._in_flight.discard(key)
        display_name = self._display_names.pop(key, "")
        entry = self._pending.get(key)
        if entry is None:
            # Inzwischen erledigt oder aufgegeben.
            return
        self._record(display_name, entry, error)

    def stop(self) -> None:
        self._delivery.stop()


__all__ = [
    "UNCONFIRMED_MAX_AGE_SECONDS",
    "BackgroundSessionClaimReporter",
    "PendingClaim",
    "SessionClaimReporter",
    "build_claim",
]
