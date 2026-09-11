"""Native Windows signout, authorized by Windows rather than shared JSON files."""
from datetime import datetime
import subprocess
import sys

from shared.status_pipe import request_agent_logoff, request_snapshot


def _session_username(session: dict) -> str:
    return session.get("full_username") or (
        ((session.get("domain") + "\\") if session.get("domain") else "")
        + (session.get("username") or "")
    )


def _verified_status_session(
    target: str,
    expected_agent_id: str | None,
    session_id: int,
    username: str,
    expected_time: datetime,
) -> dict:
    """Read a fresh STATUS/1 response and reject a changed/reused session ID."""
    try:
        snapshot, _elapsed = request_snapshot(target)
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code is None and exc.args and isinstance(exc.args[0], int):
            code = exc.args[0]
        raise RuntimeError(
            f"Die Sitzung konnte nicht frisch über den Agentstatus geprüft werden "
            f"(Fehler {code or type(exc).__name__})."
        ) from exc
    if (
        expected_agent_id
        and snapshot.workstation_id.strip().casefold()
        != expected_agent_id.strip().casefold()
    ):
        raise ValueError(
            "Der antwortende Agent passt nicht zur Maschine. Agent-Zuordnung prüfen."
        )
    session = next(
        (
            item
            for item in snapshot.rdp_sessions
            if item.get("session_id") == session_id
            and item.get("session_state")
            in ("connected", "disconnected", "reconnected", "logon")
        ),
        None,
    )
    if session is None:
        raise ValueError("Die Sitzung wird vom Agenten nicht mehr als aktiv gemeldet.")
    if _session_username(session).casefold() != username.casefold():
        raise ValueError("Der Benutzer der Sitzung hat sich geändert.")
    actual_login = session.get("login_time")
    try:
        actual_time = datetime.fromisoformat(actual_login) if actual_login else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Der aktuelle Anmeldezeitpunkt ist nicht prüfbar.") from exc
    if actual_time is None or actual_time.tzinfo is None or actual_time != expected_time:
        raise ValueError("Der Anmeldezeitpunkt der Sitzung hat sich geändert.")
    return session


def _helper_command(target: str, session_id: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--session-logoff-helper", target, str(session_id)]
    return [
        sys.executable,
        "-m",
        "portal_app.session_logoff_helper",
        target,
        str(session_id),
    ]


def _request_windows_logoff(target: str, session_id: int) -> None:
    """Keep native WTS failures outside the long-running Qt process."""
    try:
        result = subprocess.run(
            _helper_command(target, session_id),
            check=False,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Die Windows-Abmeldung hat innerhalb von 30 Sekunden nicht geantwortet."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "Der geschützte Windows-Hilfsprozess für die Abmeldung konnte nicht gestartet werden."
        ) from exc
    if result.returncode:
        raise OSError(
            result.returncode,
            f"Windows hat die Abmeldung abgelehnt (Fehler {result.returncode}).",
        )


def _confirm_session_ended(
    target: str,
    expected_agent_id: str | None,
    session_id: int,
    username: str,
    expected_time: datetime,
) -> None:
    """Accept success only after STATUS/1 no longer reports the exact old session."""
    try:
        snapshot, _elapsed = request_snapshot(target)
    except Exception as exc:
        code = getattr(exc, "winerror", None)
        if code is None and exc.args and isinstance(exc.args[0], int):
            code = exc.args[0]
        raise RuntimeError(
            "Windows hat den Abmeldeaufruf beendet, aber der Agent konnte das "
            f"Sitzungsende nicht bestätigen (Fehler {code or type(exc).__name__})."
        ) from exc
    if (
        expected_agent_id
        and snapshot.workstation_id.strip().casefold()
        != expected_agent_id.strip().casefold()
    ):
        raise RuntimeError(
            "Nach der Windows-Abmeldung antwortet ein anderer Agent. "
            "Das Sitzungsende ist nicht bestätigt."
        )
    for session in snapshot.rdp_sessions:
        try:
            observed_time = datetime.fromisoformat(session.get("login_time") or "")
        except (TypeError, ValueError):
            observed_time = None
        if (
            session.get("session_id") == session_id
            and session.get("session_state")
            in ("connected", "disconnected", "reconnected", "logon")
            and _session_username(session).casefold() == username.casefold()
            and observed_time == expected_time
        ):
            raise RuntimeError(
                "Windows hat den Abmeldeaufruf beendet, aber der Agent meldet "
                "dieselbe Sitzung weiterhin als aktiv. Sie wurde nicht als abgemeldet bestätigt."
            )


def _logoff_session(
    target: str,
    session_id: int,
    username: str,
    login_time: str,
    expected_agent_id: str | None,
    status_target: str | None,
    *,
    require_owner: bool,
    admin_credentials: tuple[str, str] | None = None,
) -> None:
    """Reject stale/reused IDs and let Windows authorize the final WTS request."""
    import win32api
    import win32con
    import win32security

    if not target or type(session_id) is not int or session_id <= 0 or not username or not login_time:
        raise ValueError("Keine eindeutig identifizierte Sitzung. Aktuelle Agent-Meldung abwarten.")
    try:
        expected_time = datetime.fromisoformat(login_time)
    except (TypeError, ValueError) as exc:
        raise ValueError("Der Anmeldezeitpunkt ist nicht prüfbar.") from exc
    if expected_time.tzinfo is None:
        raise ValueError("Der Anmeldezeitpunkt enthält keine Zeitzone.")
    verified_target = status_target or target
    _verified_status_session(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
    )
    if require_owner:
        try:
            session_sid, _, _ = win32security.LookupAccountName(None, username)
        except Exception as exc:
            raise ValueError(
                "Die Windows-Benutzerkennung der Sitzung kann auf diesem Portal-PC "
                "nicht dem aktuellen Konto zugeordnet werden."
            ) from exc
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_QUERY,
        )
        try:
            caller_sid = win32security.GetTokenInformation(
                token,
                win32security.TokenUser,
            )[0]
        finally:
            token.Close()
        if session_sid != caller_sid:
            raise ValueError(
                "Die Sitzung gehört nicht deinem aktuellen Windows-Konto. "
                "Verbinde dich mit dem Sitzungskonto erneut und melde dich dort "
                "über Start → Benutzer → Abmelden ab."
            )
    # Check the read-only live status again immediately before asking Windows.
    _verified_status_session(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
    )
    # The local SYSTEM agent performs the final WTS call. For an own session it
    # independently checks user and RDP client computer; an administrative
    # request must authenticate as an administrator of the target computer.
    request_agent_logoff(
        verified_target,
        session_id,
        username,
        login_time,
        username,
        expected_agent_id,
        administrative=not require_owner,
        credentials=admin_credentials,
    )
    _confirm_session_ended(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
    )


def logoff_own_session(
    target: str,
    session_id: int,
    username: str,
    login_time: str,
    expected_agent_id: str | None = None,
    status_target: str | None = None,
) -> None:
    """Sign out only a session whose Windows SID matches the portal process token."""
    _logoff_session(
        target,
        session_id,
        username,
        login_time,
        expected_agent_id,
        status_target,
        require_owner=True,
    )


def logoff_admin_session(
    target: str,
    session_id: int,
    username: str,
    login_time: str,
    expected_agent_id: str | None = None,
    status_target: str | None = None,
    admin_credentials: tuple[str, str] | None = None,
) -> None:
    """Request an emergency signout; the target Windows host enforces admin rights."""
    _logoff_session(
        target,
        session_id,
        username,
        login_time,
        expected_agent_id,
        status_target,
        require_owner=False,
        admin_credentials=admin_credentials,
    )


__all__ = ["logoff_admin_session", "logoff_own_session"]
