"""One definition of how a reported session names its Windows user.

The portal compares this string against the account the user picked, against the
Windows token that owns a session, and against what the agent reports.  It used
to be rebuilt inline in five places across four modules, each re-implementing
``WTSSessionInfo.full_username`` against a dict.  A divergence between two copies
would make the ownership check and the display disagree, so the rule lives here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shared.enums import SessionState

#: States in which a session still holds the machine and blocks a new connection.
#: The agent compares typed WTSSessionInfo.session_state values against this set.
ACTIVE_SESSION_STATES: frozenset[SessionState] = frozenset(
    {
        SessionState.CONNECTED,
        SessionState.DISCONNECTED,
        SessionState.RECONNECTED,
        SessionState.LOGON,
    }
)

#: The same rule for the portal, which reads session_state out of agent JSON.
ACTIVE_SESSION_STATE_VALUES: frozenset[str] = frozenset(
    state.value for state in ACTIVE_SESSION_STATES
)


def session_username(session: Mapping[str, Any]) -> str:
    """Return ``DOMAIN\\user`` for one reported session, or ``""`` if unknown.

    ``full_username`` wins when the agent supplied it; otherwise this joins domain
    and user name exactly as ``WTSSessionInfo.full_username`` does -- including the
    case of a domain without a user name, where a session has no owner and the
    result must be empty.  The previous inline copies produced a bare ``DOMAIN\\``
    there, which the agent's ownership check would never match.
    """
    reported = session.get("full_username")
    if reported:
        return str(reported)
    domain = session.get("domain")
    username = session.get("username")
    if domain and username:
        return f"{domain}\\{username}"
    return str(username or "")


def is_active_session(session: Mapping[str, Any]) -> bool:
    """Whether a reported session still occupies the machine."""
    return session.get("session_state") in ACTIVE_SESSION_STATE_VALUES


def is_console_session(session: Mapping[str, Any]) -> bool:
    r"""Whether a reported session is the local console rather than an RDP session.

    This decides which sessions the owner logoff path can handle at all: a console
    session has no RDP client, so Windows can prove nothing about who is asking.

    **Der Stationsname entscheidet, nicht das Protokoll.** Vorher stand es
    umgekehrt, und das war falsch: ``WTSClientProtocolType`` beschreibt den
    *gerade angehängten* Client, nicht die Art der Sitzung. Sobald eine
    RDP-Sitzung getrennt wird, hängt kein Client mehr daran und Windows meldet
    0 -- denselben Wert wie für die Konsole. Damit galt **jede getrennte
    RDP-Sitzung als Konsolensitzung**, also ausgerechnet der häufigste Fall:
    Wer sein Fenster schließt statt sich abzumelden, landet genau dort.

    Sichtbar war das als "Konsole am Gerät" bei einer Person, die von einem
    anderen Standort verbunden war, und als Abmeldung, die mit der Begründung
    "lokale Konsolensitzung" verweigert wurde, obwohl gar keine vorlag.

    Nachgemessen an den WinStation-Namen dieses Rechners: Die RDP-Station
    ``RDP-Tcp`` meldet ``protocol_type`` 0, sobald kein Client daran hängt,
    während ``RDP-Tcp#1`` mit Client 2 meldet. Der Name bleibt in beiden Fällen
    gleich -- er gehört zur Sitzung, das Protokoll zur Verbindung.

    Im Zweifel *keine* Konsole: Der Agent prüft die Berechtigung ohnehin selbst
    und weist eine echte Konsolensitzung dann mit eigener Begründung ab. Eine
    falsche Vermutung kostet hier einen abgelehnten Versuch, kein Recht.
    """
    station = str(session.get("display_name") or "").strip().upper()
    if station.startswith("RDP-"):
        return False
    if station == "CONSOLE":
        return True
    if session.get("protocol_type") == 2:
        return False
    return bool(session.get("is_console_session"))


def host_aliases(value: Any) -> set[str]:
    """Vergleichbare Formen eines Rechnernamens oder einer Adresse.

    Kleingeschrieben, ohne führende Backslashes, ohne Zonenangabe einer
    IPv6-Adresse und zusätzlich ohne Domänenteil -- ``NB12KI.firma.local``
    und ``NB12KI`` bezeichnen denselben Rechner.
    """
    from ipaddress import ip_address

    text = str(value or "").strip().lstrip("\\").strip("[]").split("%", 1)[0].rstrip(".")
    text = text.casefold()
    if not text:
        return set()
    try:
        return {str(ip_address(text))}
    except ValueError:
        return {text, text.split(".", 1)[0]}


def claim_matches_session_client(claim: Mapping[str, Any], session: Mapping[str, Any]) -> bool:
    """Ob eine Sitzung von dem Rechner aus aufgebaut wurde, der die Meldung schickte.

    Eine Aufschaltmeldung entsteht beim Start von mstsc, die Sitzung erst
    danach. Ohne diese Prüfung hängte sich eine Meldung an *irgendeine*
    Sitzung des Kontos -- auch an die eines Kollegen an einem anderen
    Standort, wenn die eigene Verbindung nie zustande kam. Die Karte nannte
    dann den Falschen. Windows meldet für jede RDP-Sitzung den verbindenden
    Rechner, und das Portal schreibt seinen Namen in die Meldung.
    """
    claimed = host_aliases(claim.get("client_name"))
    reported = host_aliases(session.get("client_name")) | host_aliases(session.get("client_address"))
    return bool(claimed & reported)


def claim_client_conflicts(claim: Mapping[str, Any], session: Mapping[str, Any]) -> bool:
    """Ob Windows für die Sitzung einen anderen verbindenden Rechner meldet.

    Für eine schon gebundene Meldung: Wechselt der Rechner, hat jemand anderes
    die Sitzung übernommen, und die alte Meldung nennt nicht mehr, wer davor
    sitzt. Fehlt eine Angabe auf einer Seite -- etwa bei einer getrennten
    Sitzung ohne Client --, ist das kein Widerspruch.
    """
    claimed = host_aliases(claim.get("client_name"))
    reported = host_aliases(session.get("client_name")) | host_aliases(session.get("client_address"))
    return bool(claimed and reported and not claimed & reported)


__all__ = [
    "ACTIVE_SESSION_STATES",
    "ACTIVE_SESSION_STATE_VALUES",
    "claim_client_conflicts",
    "claim_matches_session_client",
    "host_aliases",
    "is_active_session",
    "is_console_session",
    "session_username",
]
