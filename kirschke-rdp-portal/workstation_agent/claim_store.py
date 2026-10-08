"""Wer sich auf diese Maschine aufgeschaltet hat, verwahrt vom Agenten.

Das Problem, für das es diesen Speicher gibt
--------------------------------------------
Auf eine Workstation schaltet sich bewusst jeder unter demselben, eigens dafür
angelegten Windows-Konto auf. Damit ist der Kontoname als Unterscheidungsmerkmal
wertlos: Der Agent meldet die Sitzung unter diesem Konto, jedes Portal vergleicht
sie mit den Konten seines Benutzers, findet dasselbe Konto -- und zeigt die
Maschine allen Beteiligten als "von dir belegt" an. Wer wirklich davor sitzt,
stand nirgends.

Das weiß nur das Portal, das die Verbindung gestartet hat. Es meldet es hierher,
und der Agent gibt es mit jedem Status-Snapshot an alle Portale zurück -- derselbe
Weg, den die Reservierungen schon gehen, und damit auch ohne gemeinsame Ablage
belastbar.

Was das ausdrücklich *nicht* ist
--------------------------------
Keine Rechtevergabe und kein Nachweis. Die Pipe wird über das gemeinsame
Konto ``PortalLeser`` erreicht, das das Portal ausweist, nie den Menschen (siehe
:mod:`workstation_agent.reservation_store` für dieselbe Grenze). Der Agent kann
also nicht prüfen, ob die Meldung stimmt.

Daraus folgt die eine Regel, an der im Portal alles hängt: Eine Meldung darf eine
Zuordnung nur *wegnehmen*, nie eine geben. Eine fremde Meldung macht eine Sitzung
zu einer fremden -- was höchstens dazu führt, dass jemand eine Maschine für
belegt hält, die ihm gehört. Umgekehrt könnte eine erfundene Meldung sonst eine
fremde Sitzung als eigene ausweisen, und daran hängt der Abmeldeweg. Siehe
``Workstation.owned_sessions``.

Bindung und Verfall
-------------------
Eine Meldung entsteht beim Start von ``mstsc``, die Windows-Sitzung erst danach.
Sie wird deshalb zunächst nur unter ihrem Kontonamen abgelegt und später an die
Sitzung gebunden, die der Agent zu diesem Konto findet. Sie verfällt, sobald
dieses Konto keine Sitzung mehr hat -- dann ist die Person weg --, und
ersatzweise nach :data:`CLAIM_MAX_AGE_SECONDS`, falls eine Verbindung nie
zustande kam.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shared.agent_snapshot import validate_session_claims
from shared.file_io import write_json_atomic
from shared.identity import account_names_session, same_account_name
from shared.session_identity import (
    claim_client_conflicts,
    claim_matches_session_client,
    is_active_session,
)

logger = logging.getLogger(__name__)

#: Dateiname neben der Agentenkonfiguration.
STORE_FILENAME = "agent-session-claims.json"

#: Obergrenze wie beim Reservierungsspeicher: Die Snapshot-Liste ist auf 32
#: Meldungen begrenzter Feldlänge gedeckelt, alles darüber kann kein gültiger
#: Speicher sein und wird gar nicht erst geparst.
MAX_STORE_BYTES = 128_000

#: Wie lange eine Meldung gilt, die nie an eine Sitzung gebunden werden konnte.
#: Großzügig bemessen: Zwischen dem Start von ``mstsc`` und der fertigen
#: Windows-Anmeldung liegen bei einer Kennwort- oder Entra-Abfrage durchaus
#: Minuten, und eine zu früh verworfene Meldung führt genau zu dem Zustand
#: zurück, den dieser Speicher beheben soll.
CLAIM_MAX_AGE_SECONDS = 1800


def default_store_path() -> Path:
    """Wo der Speicher liegt: neben der Konfiguration des Agenten."""
    configured = os.getenv("AGENT_CONFIG_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().parent / STORE_FILENAME
    data_root = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    return data_root / "KirschkeRDPAgent" / STORE_FILENAME


def _is_same_session(claim: dict[str, Any], session: dict[str, Any] | None) -> bool:
    """Ob eine gebundene Meldung genau zu dieser Sitzung gehört.

    Sitzungsnummer *und* Anmeldezeitpunkt, denn Windows vergibt Nummern neu.
    Ohne den Zeitpunkt zählte die nächste Anmeldung unter derselben Nummer als
    dieselbe Sitzung -- und auf einer Maschine mit einem gemeinsamen Konto ist
    genau das der Regelfall, nicht die Ausnahme.
    """
    if session is None:
        return False
    return claim.get("session_id") == session.get("session_id") and str(
        claim.get("login_time") or ""
    ) == str(session.get("login_time") or "")


def _age_seconds(value: Any, now: datetime) -> float | None:
    """Alter einer Meldung in Sekunden, oder ``None`` bei unlesbarem Zeitstempel."""
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp).total_seconds()


class SessionClaimStore:
    """Die Aufschaltmeldungen dieser Maschine, über Neustarts hinweg.

    Durch ein Lock geschützt, weil der Pipe-Handler schreibt, während der
    Snapshot-Bauer liest, und beide auf verschiedenen Threads laufen.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_store_path()
        self._lock = threading.Lock()
        self._claims: list[dict[str, Any]] = []
        self._loaded = False

    def _load_unlocked(self) -> None:
        """Einmal einlesen, jede Art beschädigter Datei verzeihend.

        Ein unlesbarer Speicher darf den Agenten nie am Starten hindern: Die
        Meldungen sind Anzeigeinformation, während der Statuskanal und der
        Abmeldeweg das sind, wofür die Maschine gebraucht wird.

        Der Aufrufer hält das Lock.
        """
        if self._loaded:
            return
        self._loaded = True
        self._claims = []
        try:
            if self.path.stat().st_size > MAX_STORE_BYTES:
                logger.warning("Aufschaltdatei zu groß, wird ignoriert: %s", self.path)
                return
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.warning("Aufschaltdatei nicht lesbar: %s", self.path, exc_info=True)
            return
        try:
            self._claims = validate_session_claims(
                raw.get("session_claims") if isinstance(raw, dict) else raw
            )
        except ValueError:
            logger.warning("Aufschaltdatei verworfen: unerwarteter Inhalt")
            self._claims = []

    def load(self) -> list[dict[str, Any]]:
        """Den gespeicherten Stand einlesen und zurückgeben."""
        with self._lock:
            self._load_unlocked()
            return list(self._claims)

    def current(self) -> list[dict[str, Any]]:
        """Die Liste für einen Snapshot."""
        return self.load()

    def _persist(self) -> None:
        """Caller hält das Lock."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(self.path, {"session_claims": self._claims})
        except OSError:
            # Die Liste bleibt im Speicher und wird weiter gemeldet, sie
            # übersteht nur keinen Neustart. Hier abzubrechen hieße, eine
            # Meldung zu verwerfen, die sonst jedes Portal sofort sieht.
            logger.warning(
                "Aufschaltungen konnten nicht gespeichert werden: %s", self.path, exc_info=True
            )

    def claim(self, claim: Any, client_computer: str = "") -> dict[str, Any]:
        """Eine gemeldete Aufschaltung übernehmen.

        Pro Windows-Konto wird genau eine geführt: Eine neue Meldung ersetzt die
        alte, weil die Frage "wer sitzt gerade davor" nur eine gültige Antwort
        hat und die jüngste Meldung die beste ist, die der Agent hat.

        "Dasselbe Konto" heißt in jeder Schreibweise: ``Rechenknecht`` und
        ``WORKSTATION\\Rechenknecht`` sind eins. Vorher zählte nur die wörtlich
        gleiche, und die Meldung des Vorgängers blieb neben der neuen stehen.
        """
        checked = validate_session_claims([claim])
        if not checked:
            raise ValueError("Leere Aufschaltmeldung.")
        record = checked[0]
        record["claimed_at_utc"] = datetime.now(UTC).isoformat()
        if client_computer and not record.get("client_name"):
            record["client_name"] = client_computer[:256]
        with self._lock:
            # Erst den gespeicherten Stand holen: Sonst ersetzt die erste
            # Meldung nach einem Neustart nicht die alte, sondern alle.
            self._load_unlocked()
            self._claims = [
                item
                for item in self._claims
                if not same_account_name(item.get("account"), record["account"])
            ]
            self._claims.append(record)
            self._persist()
        return dict(record)

    def bind_and_expire(self, sessions: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
        """Meldungen an die tatsächlichen Sitzungen binden und Abgelaufenes entfernen.

        Wird vor jedem Snapshot aufgerufen, weil der Agent hier als Einziger
        beides sieht: die gemeldete Aufschaltung und die Sitzung, die daraus
        geworden ist.

        Eine Meldung fällt weg, sobald ihr Konto keine aktive Sitzung mehr hat.
        Solange sie noch keine gefunden hat, gilt die Frist aus
        :data:`CLAIM_MAX_AGE_SECONDS` -- eine Verbindung, die nie zustande kam,
        soll die Maschine nicht dauerhaft jemandem zuschreiben.
        """
        moment = now or datetime.now(UTC)
        active = [item for item in sessions if is_active_session(item)]
        kept: list[dict[str, Any]] = []
        with self._lock:
            self._load_unlocked()
            for record in self._claims:
                # Die Meldung trägt die Schreibweise des Portals, die Sitzung
                # die von Windows. Wörtlich verglichen fand eine Meldung als
                # "Rechenknecht" die Sitzung "WORKSTATION\Rechenknecht" nie.
                matching = [
                    item for item in active
                    if account_names_session(record.get("account"), item)
                ]
                bound = record.get("session_id") is not None
                # Gebunden wird nur an eine Sitzung, die vom meldenden Rechner
                # aus aufgebaut wurde. Kam die eigene Verbindung nie zustande,
                # hängte sich die Meldung sonst an die Sitzung eines Kollegen
                # unter demselben Konto -- und die Karte nannte den Falschen.
                fresh = [
                    item for item in matching
                    if claim_matches_session_client(record, item)
                ]
                session = next(
                    (
                        item for item in matching
                        if _is_same_session(record, item)
                        and not claim_client_conflicts(record, item)
                    ),
                    fresh[0] if fresh and not bound else None,
                )
                if bound and not _is_same_session(record, session):
                    # Gebunden, aber die Sitzung ist weg oder es ist eine andere
                    # unter demselben Konto. Genau darauf kommt es auf einer
                    # Maschine an, auf der sich alle unter einem gemeinsamen
                    # Konto anmelden: Meldet sich jemand ab und der Nächste an,
                    # hätte sich die alte Meldung sonst an die neue Sitzung
                    # gehängt -- und die Maschine wäre für alle "belegt durch"
                    # eine Person, die längst weg ist.
                    continue
                if session is not None:
                    record = dict(record)
                    record["session_id"] = session.get("session_id")
                    record["login_time"] = session.get("login_time")
                    kept.append(record)
                    continue
                age = _age_seconds(record.get("claimed_at_utc"), moment)
                if age is None or age <= CLAIM_MAX_AGE_SECONDS:
                    kept.append(dict(record))
            changed = kept != self._claims
            self._claims = kept
            if changed:
                self._persist()
            return list(self._claims)

    def handle(self, command: dict, client_computer: str) -> dict:
        """Eine ``CLAIM/1``-Anfrage eines Portals beantworten."""
        if not isinstance(command, dict) or command.get("protocol") != "CLAIM/1":
            raise ValueError("Unerwartetes Aufschaltprotokoll.")
        record = self.claim(command.get("claim"), client_computer)
        logger.info(
            "Aufschaltung von %s übernommen: %s als %s.",
            client_computer or "unbekannt",
            record.get("owner_upn"),
            record.get("account"),
        )
        return {"ok": True, "account": record.get("account")}


__all__ = [
    "CLAIM_MAX_AGE_SECONDS",
    "MAX_STORE_BYTES",
    "STORE_FILENAME",
    "SessionClaimStore",
    "default_store_path",
]
