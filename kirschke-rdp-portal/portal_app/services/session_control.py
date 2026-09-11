"""Native Windows signout, authorized by Windows rather than shared JSON files."""
from datetime import datetime


def logoff_own_session(target: str, session_id: int, username: str, login_time: str) -> None:
    """Reject stale/reused session IDs and other users, including for administrators."""
    import win32api
    import win32con
    import win32security
    import win32ts
    from workstation_agent.wts.monitor import WTSMonitor

    if not target or type(session_id) is not int or session_id <= 0 or not username or not login_time:
        raise ValueError("Keine eindeutig identifizierte Sitzung. Aktuelle Agent-Meldung abwarten.")
    expected_time = datetime.fromisoformat(login_time)
    if expected_time.tzinfo is None:
        raise ValueError("Der Anmeldezeitpunkt enthält keine Zeitzone.")
    with WTSMonitor(target) as monitor:
        def verify():
            session = monitor.get_session(session_id)
            if (session is None or session.full_username.casefold() != username.casefold()
                    or session.login_time != expected_time):
                raise ValueError("Die Sitzung hat sich geändert oder lässt sich nicht prüfen. Agentstatus neu einlesen.")
            return session

        session = verify()
        remote_sid, _, _ = win32security.LookupAccountName(target, session.full_username)
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        try:
            caller_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        finally:
            token.Close()
        if remote_sid != caller_sid:
            raise ValueError("Die Sitzung gehört nicht deinem aktuellen Windows-Konto. "
                             "Verbinde dich mit dem Sitzungskonto erneut und melde dich dort über Start → Benutzer → Abmelden ab.")
        handle = win32ts.WTSOpenServer(target)
        try:
            verify()
            # Asynchronous request: do not mark the dashboard free until the agent confirms it.
            win32ts.WTSLogoffSession(handle, session_id, False)
        finally:
            win32ts.WTSCloseServer(handle)
