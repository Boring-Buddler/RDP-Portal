"""Native Windows signout, authorized by Windows rather than shared JSON files."""
from datetime import datetime

from portal_app.services.agent_identity import match_agent, mismatch_message
from shared.session_identity import is_active_session, is_console_session, session_username
from shared.status_pipe import request_agent_logoff, request_snapshot

#: Shown whenever this portal process is not the account that owns the session.
NOT_YOUR_SESSION = (
    "Die Sitzung gehört nicht deinem aktuellen Windows-Konto. "
    "Verbinde dich mit dem Sitzungskonto erneut und melde dich dort "
    "über Start → Benutzer → Abmelden ab."
)

#: A local console session has no RDP client, so nothing about the requester can
#: be proven to the agent.  See :mod:`workstation_agent.session_control`.
CONSOLE_SESSION_NOT_OWN = (
    "Das ist eine lokale Konsolensitzung am Gerät selbst. Für sie kann Windows "
    "keinen anfragenden RDP-Client bestätigen, deshalb lässt der Agent die normale "
    "Abmeldung nicht zu. Möglich sind: am Gerät abmelden, die Sitzung per RDP "
    "übernehmen und dort abmelden, oder die administrative Abmeldung."
)


def _process_sid() -> str:
    """The SID of the Windows account this portal process runs as."""
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32con.TOKEN_QUERY,
    )
    try:
        return str(
            win32security.ConvertSidToStringSid(
                win32security.GetTokenInformation(token, win32security.TokenUser)[0]
            )
        )
    finally:
        token.Close()


def _require_own_account(session: dict, username: str) -> None:
    """Refuse unless this portal process runs as the account owning the session.

    The SID the agent read from the session's own token decides.  It is the form
    Windows authorizes against, and unlike a name it does not depend on this PC
    having the account cached -- the lookup that fails for Entra accounts whose
    profile lives only on the target.  Resolving the name locally stays as a
    fallback for agents too old to report a SID.
    """
    import win32security

    caller = _process_sid()
    reported = str(session.get("sid") or "").strip()
    if reported:
        if reported.casefold() != caller.casefold():
            raise ValueError(NOT_YOUR_SESSION)
        return
    try:
        session_sid = win32security.ConvertSidToStringSid(
            win32security.LookupAccountName(None, username)[0]
        )
    except Exception as exc:
        raise ValueError(
            "Der Agent hat für diese Sitzung keine Windows-SID gemeldet, und der "
            "Kontoname lässt sich auf diesem Portal-PC nicht auflösen. Das ist bei "
            "Entra-Konten normal, deren Profil nur auf dem Zielrechner existiert. "
            "Agent aktualisieren oder am Zielrechner abmelden."
        ) from exc
    if session_sid.casefold() != caller.casefold():
        raise ValueError(NOT_YOUR_SESSION)


def _require_matching_agent(snapshot, expected_agent_id, hostnames) -> None:
    """Refuse to act unless the agent that answered belongs to this machine.

    Uses the same rule the status channel uses, so a machine cannot show a healthy
    live status and then refuse every logoff over a mismatch nobody can see.

    ``hostnames`` carries the machine's own host names as additional evidence, for
    the usual case where no agent was assigned by hand and the portal's generated
    machine ID therefore differs from what the agent calls itself.  ``None`` means
    somebody pinned the mapping explicitly, and then only the ID may decide.
    """
    if not expected_agent_id:
        return
    match = match_agent(
        expected_id=expected_agent_id,
        assigned_explicitly=hostnames is None,
        hostnames=hostnames or set(),
        reported_id=snapshot.workstation_id,
        reported_hostname=snapshot.hostname,
    )
    if not match:
        raise ValueError(
            mismatch_message(
                expected_agent_id,
                expected_agent_id,
                snapshot.workstation_id,
                snapshot.hostname,
                match.reason,
            )
        )


def _verified_status_session(
    target: str,
    expected_agent_id: str | None,
    session_id: int,
    username: str,
    expected_time: datetime,
    hostnames: set[str] | None = None,
) -> tuple[dict, object]:
    """Read a fresh STATUS/1 response and reject a changed/reused session ID.

    Returns the verified session together with the snapshot it came from: the
    agent identifies itself by its own ID, and that is the one the logoff request
    has to carry, not the portal's generated machine ID.
    """
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
    _require_matching_agent(snapshot, expected_agent_id, hostnames)
    session = next(
        (
            item
            for item in snapshot.rdp_sessions
            if item.get("session_id") == session_id and is_active_session(item)
        ),
        None,
    )
    if session is None:
        raise ValueError("Die Sitzung wird vom Agenten nicht mehr als aktiv gemeldet.")
    if session_username(session).casefold() != username.casefold():
        raise ValueError("Der Benutzer der Sitzung hat sich geändert.")
    actual_login = session.get("login_time")
    try:
        actual_time = datetime.fromisoformat(actual_login) if actual_login else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Der aktuelle Anmeldezeitpunkt ist nicht prüfbar.") from exc
    if actual_time is None or actual_time.tzinfo is None or actual_time != expected_time:
        raise ValueError("Der Anmeldezeitpunkt der Sitzung hat sich geändert.")
    return session, snapshot


def _confirm_session_ended(
    target: str,
    expected_agent_id: str | None,
    session_id: int,
    username: str,
    expected_time: datetime,
    hostnames: set[str] | None = None,
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
    try:
        _require_matching_agent(snapshot, expected_agent_id, hostnames)
    except ValueError as exc:
        raise RuntimeError(
            "Nach der Windows-Abmeldung antwortet ein anderer Agent. "
            f"Das Sitzungsende ist damit nicht bestätigt.\n\n{exc}"
        ) from exc
    for session in snapshot.rdp_sessions:
        try:
            observed_time = datetime.fromisoformat(session.get("login_time") or "")
        except (TypeError, ValueError):
            observed_time = None
        if (
            session.get("session_id") == session_id
            and is_active_session(session)
            and session_username(session).casefold() == username.casefold()
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
    hostnames: set[str] | None = None,
) -> None:
    """Reject stale/reused IDs and let Windows authorize the final WTS request."""
    if not target or type(session_id) is not int or session_id <= 0 or not username or not login_time:
        raise ValueError("Keine eindeutig identifizierte Sitzung. Aktuelle Agent-Meldung abwarten.")
    try:
        expected_time = datetime.fromisoformat(login_time)
    except (TypeError, ValueError) as exc:
        raise ValueError("Der Anmeldezeitpunkt ist nicht prüfbar.") from exc
    if expected_time.tzinfo is None:
        raise ValueError("Der Anmeldezeitpunkt enthält keine Zeitzone.")
    verified_target = status_target or target
    verified, snapshot = _verified_status_session(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
        hostnames,
    )
    # From here on the agent is addressed by the ID it calls itself. The portal's
    # machine ID is generated and routinely differs; the agent checks the ID in the
    # request against its own and would refuse anything else.
    agent_id = snapshot.workstation_id or expected_agent_id
    if require_owner:
        if is_console_session(verified):
            # Refuse here rather than letting the agent do it, so the reason
            # names the console session instead of a mismatched RDP client.
            raise ValueError(CONSOLE_SESSION_NOT_OWN)
        _require_own_account(verified, username)
    # Check the read-only live status again immediately before asking Windows.
    _verified_status_session(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
        hostnames,
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
        agent_id,
        administrative=not require_owner,
        credentials=admin_credentials,
    )
    _confirm_session_ended(
        verified_target,
        expected_agent_id,
        session_id,
        username,
        expected_time,
        hostnames,
    )


def logoff_own_session(
    target: str,
    session_id: int,
    username: str,
    login_time: str,
    expected_agent_id: str | None = None,
    status_target: str | None = None,
    hostnames: set[str] | None = None,
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
        hostnames=hostnames,
    )


def logoff_admin_session(
    target: str,
    session_id: int,
    username: str,
    login_time: str,
    expected_agent_id: str | None = None,
    status_target: str | None = None,
    admin_credentials: tuple[str, str] | None = None,
    hostnames: set[str] | None = None,
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
        hostnames=hostnames,
    )


__all__ = ["logoff_admin_session", "logoff_own_session"]
