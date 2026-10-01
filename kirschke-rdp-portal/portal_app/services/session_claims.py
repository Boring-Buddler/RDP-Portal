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
from dataclasses import dataclass, field
from datetime import UTC, datetime

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


class SessionClaimReporter:
    """Hält offene Aufschaltmeldungen fest, bis der Agent sie hat.

    Eine Meldung gilt als erledigt, sobald der Agent sie bestätigt -- oder
    sobald er sie im Snapshot zurückmeldet, was dasselbe beweist und auch dann
    greift, wenn die Bestätigung unterwegs verloren ging.

    Aufgegeben wird nur, wenn es nichts mehr zu melden gibt: Die Maschine führt
    keine Sitzung unter diesem Konto und die Meldung ist älter als
    :data:`UNCONFIRMED_MAX_AGE_SECONDS`.
    """

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

    def _attempt(self, workstation: Workstation, user: User, entry: PendingClaim) -> str:
        entry.attempts += 1
        try:
            target = workstation.get_agent_status_target()
        except ValueError as exc:
            entry.last_error = str(exc)
            return f"Kein Agentenziel für {workstation.display_name}: {exc}"
        try:
            push_session_claim(target, build_claim(user, entry.account))
        except Exception as exc:  # noqa: BLE001 - jede Pipe-Störung ist hier gleichwertig
            entry.last_error = str(exc)
            logger.info(
                "Aufschaltung für %s (Versuch %d) nicht zugestellt: %s",
                workstation.display_name,
                entry.attempts,
                exc,
            )
            return str(exc)
        self._pending.pop(self._key(entry.workstation_id, entry.account), None)
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


__all__ = [
    "UNCONFIRMED_MAX_AGE_SECONDS",
    "PendingClaim",
    "SessionClaimReporter",
    "build_claim",
]
