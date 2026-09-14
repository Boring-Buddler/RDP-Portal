"""Authorization and execution of exact-session logoff requests on the agent."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from ipaddress import ip_address

from shared.session_identity import ACTIVE_SESSION_STATES
from workstation_agent.wts.monitor import WTSMonitor, WTSSessionInfo

#: Kept as a module name for readability; the rule itself lives in shared so the
#: agent's authorization and the portal's display cannot drift apart.
ACTIVE_STATES = ACTIVE_SESSION_STATES


def _machine_aliases(value: str | None) -> set[str]:
    value = (value or "").strip().lstrip("\\").strip("[]").split("%", 1)[0].rstrip(".").casefold()
    try:
        return {str(ip_address(value))}
    except ValueError:
        pass
    return {value, value.split(".", 1)[0]} if value else set()


def _parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} fehlt.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} ist ungültig.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} enthält keine Zeitzone.")
    return parsed.astimezone(UTC)


class AgentSessionController:
    """Validate requester, session identity, freshness and replay before logoff."""

    def __init__(self, workstation_id: str, after_logoff=None) -> None:
        self.workstation_id = workstation_id
        self.after_logoff = after_logoff
        self._seen: dict[str, datetime] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _matching_session(command: dict, sessions: list[WTSSessionInfo]) -> WTSSessionInfo:
        session_id = command.get("session_id")
        if type(session_id) is not int or session_id <= 0:
            raise ValueError("Keine gültige Windows-Sitzungsnummer angegeben.")
        username = command.get("username")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Der Sitzungsbenutzer fehlt.")
        login_time = _parse_time(command.get("login_time"), "Der Anmeldezeitpunkt")
        session = next((item for item in sessions if item.session_id == session_id), None)
        if session is None or session.session_state not in ACTIVE_STATES:
            raise ValueError("Die Sitzung wird vom Agenten nicht mehr als aktiv gemeldet.")
        if session.full_username.casefold() != username.strip().casefold():
            raise ValueError("Der Benutzer der Sitzung hat sich geändert.")
        if session.login_time is None or session.login_time.astimezone(UTC) != login_time:
            raise ValueError("Der Anmeldezeitpunkt der Sitzung hat sich geändert.")
        return session

    def _accept_fresh_request(self, command: dict) -> None:
        expected = command.get("expected_agent_id")
        if not isinstance(expected, str) or expected.strip().casefold() != self.workstation_id.casefold():
            raise PermissionError("Die Agent-ID der Abmeldeanfrage passt nicht zu diesem Rechner.")
        request_id = command.get("request_id")
        if not isinstance(request_id, str) or not 16 <= len(request_id) <= 64:
            raise ValueError("Die Abmeldeanfrage besitzt keine gültige Vorgangs-ID.")
        requested_at = _parse_time(command.get("requested_at_utc"), "Der Anfragezeitpunkt")
        now = datetime.now(UTC)
        age = (now - requested_at).total_seconds()
        if age < -5 or age > 30:
            raise PermissionError("Die Abmeldeanfrage ist nicht mehr aktuell.")
        with self._lock:
            self._seen = {
                key: value for key, value in self._seen.items()
                if (now - value).total_seconds() <= 60
            }
            if request_id in self._seen:
                raise PermissionError("Diese Abmeldeanfrage wurde bereits verarbeitet.")
            self._seen[request_id] = now

    @staticmethod
    def _authorize_owner(command: dict, session: WTSSessionInfo, client_computer: str) -> None:
        requester = command.get("requester_identity")
        if not isinstance(requester, str) or requester.strip().casefold() != session.full_username.casefold():
            raise PermissionError("Die Sitzung gehört nicht zum angemeldeten Portal-Benutzer.")
        if not session.is_rdp_session:
            # A console session has no RDP client, so there is nothing Windows can
            # attest about the requester.  The named pipe is reached through the
            # shared PortalLeser account, which identifies the portal but not the
            # person, so the request carries no proof at all here.
            raise PermissionError(
                "Das ist eine lokale Konsolensitzung. Für sie kann Windows keinen "
                "anfragenden RDP-Client bestätigen; möglich sind nur die Abmeldung "
                "am Gerät selbst oder die administrative Abmeldung."
            )
        reported_client = _machine_aliases(session.client_name) | _machine_aliases(
            getattr(session, "client_address", None)
        )
        if not (reported_client & _machine_aliases(client_computer)):
            raise PermissionError(
                "Der anfragende Rechner stimmt nicht mit dem vom Agenten gemeldeten RDP-Client überein."
            )

    def handle(self, command: dict, client_computer: str, client_is_admin: bool) -> dict:
        if not isinstance(command, dict) or command.get("protocol") != "LOGOFF/1":
            raise ValueError("Ungültige Abmeldeanfrage.")
        self._accept_fresh_request(command)
        with WTSMonitor() as monitor:
            session = self._matching_session(command, monitor.get_user_sessions())
            if command.get("administrative") is True:
                if not client_is_admin:
                    raise PermissionError(
                        "Das angegebene Windows-Konto ist auf dem Zielrechner kein Administrator."
                    )
            else:
                self._authorize_owner(command, session, client_computer)
            monitor.logoff_session(session.session_id, wait=True)
        if self.after_logoff is not None:
            self.after_logoff()
        return {
            "ok": True,
            "message": f"Der Agent hat {session.full_username} aus Sitzung {session.session_id} abgemeldet.",
        }


__all__ = ["AgentSessionController"]
