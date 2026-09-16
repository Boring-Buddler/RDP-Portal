"""Connect to an SMB status folder without exposing credentials to a shell."""
import re
from pathlib import Path, PureWindowsPath


def parse_share_path(value: str) -> tuple[str, str, str]:
    value = value.strip()
    if not value.startswith("\\\\") or any(c in value for c in '\x00\r\n/:*?"<>|'):
        raise ValueError(r"Bitte einen Netzwerkpfad wie \\Remote-Ettlingen\RDP-Status eingeben.")
    parts = value[2:].rstrip("\\").split("\\")
    if len(parts) < 2 or any(not p or p in {".", ".."} or p.endswith((".", " ")) for p in parts):
        raise ValueError("Rechnername und Freigabename müssen vollständig angegeben werden.")
    server = parts[0]
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", server):
        raise ValueError("Ungültiger Rechnername im Netzwerkpfad.")
    return str(PureWindowsPath(value)).rstrip("\\"), server, "\\\\" + "\\".join(parts[:2])


def credential_payload(server: str, username: str, password: str) -> dict:
    import win32cred

    return {
        "Type": win32cred.CRED_TYPE_DOMAIN_PASSWORD,
        "TargetName": server,
        "UserName": username,
        # PyWin32's CredWrite wrapper performs UTF-16 conversion itself.
        # Passing encoded bytes raises TypeError before Windows is called.
        "CredentialBlob": password,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": "RDP-Portal: SMB-Statusfreigabe",
    }


def connect_share(path: str, username: str, password: str, remember: bool) -> tuple[str, str]:
    import pywintypes
    import win32cred
    import win32wnet

    path, server, root = parse_share_path(path)
    username = username.strip()
    if not username or not password:
        raise ValueError("Benutzername und Kennwort der Freigabe fehlen.")
    if any(c in username + password for c in "\x00\r\n"):
        raise ValueError("Die Zugangsdaten enthalten unzulässige Steuerzeichen.")
    if "\\" not in username and "@" not in username:
        username = server + "\\" + username
    resource = win32wnet.NETRESOURCE()
    resource.dwType = 1  # RESOURCETYPE_DISK
    resource.lpRemoteName = root
    try:
        # Deviceless connection in the caller's Windows logon session. Never
        # cancel another application's SMB connections to resolve conflicts.
        win32wnet.WNetAddConnection2(resource, password, username, 0)
        files = sorted(Path(path).iterdir())
        json_files = [item for item in files if item.suffix.casefold() == ".json"]
        for item in json_files:
            with item.open("rb") as stream:
                stream.read(1)
    except pywintypes.error as exc:
        code = exc.winerror
        if code == 1219:
            raise ValueError("Windows ist mit diesem Rechner bereits unter einem anderen Konto verbunden. "
                             "Bestehende Freigaben zuerst regulär schließen oder dasselbe Konto verwenden. "
                             "Das Portal trennt keine anderen Verbindungen.") from None
        raise ValueError(f"Windows konnte die Freigabe nicht verbinden (Fehler {code}). "
                         "VPN, Freigabename, Benutzername, Kennwort und Berechtigungen prüfen.") from None
    except OSError:
        raise ValueError("Verbindung hergestellt, aber der Statusordner oder seine JSON-Dateien sind nicht lesbar.") from None
    if remember:
        try:
            win32cred.CredWrite(credential_payload(server, username, password), 0)
        except (pywintypes.error, TypeError, ValueError) as exc:
            error = getattr(exc, "winerror", None)
            detail = f"Windows-Fehler {error}" if error is not None else type(exc).__name__
            raise ValueError(f"Freigabe erreichbar, aber die Zugangsdaten konnten nicht gespeichert werden ({detail}). "
                             "Ohne Speicherung erneut verbinden oder die Windows-Richtlinie prüfen.") from None
    return path, f"Freigabe erreichbar; {len(json_files)} JSON-Datei(en) lesbar."


# --- Shared reader account -------------------------------------------------
#
# Every target machine's agent setup creates the same read-only PortalLeser
# account.  Connecting each status share by hand, once per machine, is what made
# the file fallback feel broken: it had to be re-entered before the agent channel
# worked at all, and nothing re-established the connection after a restart.
#
# A password entered here is kept where Windows keeps passwords, never in a
# portal file.  A password shipped with the release lives in
# portal_app.services.reader_account, which explains what that exposes.

#: Credential Manager entry holding the reader account this user has confirmed.
#: Generic rather than DOMAIN_PASSWORD: it is the portal's own note about which
#: account to use, not the per-server entry Windows consults for SMB itself.
READER_CREDENTIAL_TARGET = "KirschkeRDPPortal:Freigabekonto"


def save_reader_credentials(username: str, password: str) -> str:
    r"""Remember the reader account for automatic share connections.

    Returns the account name as stored. A bare name is kept bare on purpose: it
    is qualified per server at connection time, because PortalLeser is a *local*
    account on each target and ``SERVER\PortalLeser`` is the only spelling that
    authenticates there.
    """
    import win32cred

    username = (username or "").strip()
    if not username or not password:
        raise ValueError("Benutzername und Kennwort des Lesekontos fehlen.")
    if any(c in username + password for c in "\x00\r\n"):
        raise ValueError("Die Zugangsdaten enthalten unzulässige Steuerzeichen.")
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": READER_CREDENTIAL_TARGET,
            "UserName": username,
            "CredentialBlob": password,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "Comment": "RDP-Portal: Lesekonto der Statusfreigaben",
        },
        0,
    )
    return username


def stored_reader_credentials() -> tuple[str, str] | None:
    """What this user confirmed, ignoring whatever the release brought along."""
    import pywintypes
    import win32cred

    try:
        entry = win32cred.CredRead(READER_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error:
        return None
    blob = entry.get("CredentialBlob")
    # CredRead hands back the raw UTF-16LE bytes CredWrite stored.
    password = (
        blob.decode("utf-16-le", errors="ignore")
        if isinstance(blob, bytes)
        else str(blob or "")
    )
    username = str(entry.get("UserName") or "").strip()
    return (username, password) if username and password else None


def load_reader_credentials() -> tuple[str, str] | None:
    """The reader account to use, or None when nobody has provided one.

    A stored password wins over the bundled one: it is there because somebody
    corrected this machine, and a release must not quietly overrule that.
    """
    from portal_app.services.reader_account import bundled_credentials

    return stored_reader_credentials() or bundled_credentials()


def reader_account_source() -> str:
    """Where the reader account in use comes from, for the settings page."""
    from portal_app.services.reader_account import has_bundled_password

    if stored_reader_credentials():
        return "stored"
    return "bundled" if has_bundled_password() else "none"


def reader_account_name() -> str:
    """The account name in use, for display, without touching the password."""
    credentials = load_reader_credentials()
    return credentials[0] if credentials else ""


def forget_reader_credentials() -> bool:
    """Drop this user's stored account, falling back to the bundled one."""
    import pywintypes
    import win32cred

    try:
        win32cred.CredDelete(READER_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error:
        return False
    return True


def ensure_share_connection(path: str, username: str = "", password: str = "") -> tuple[bool, str]:
    """Establish the SMB session for one status share without raising.

    Used at every portal start and after a sweep, where a machine that is simply
    switched off must cost one line in a report and nothing else.

    With no credentials it asks Windows to use whatever it has stored for that
    server, which is the normal case once a share has been connected before.
    """
    import pywintypes
    import win32wnet

    try:
        path, server, root = parse_share_path(path)
    except ValueError as exc:
        return False, str(exc)
    if username and "\\" not in username and "@" not in username:
        username = server + "\\" + username
    resource = win32wnet.NETRESOURCE()
    resource.dwType = 1  # RESOURCETYPE_DISK
    resource.lpRemoteName = root
    try:
        win32wnet.WNetAddConnection2(resource, password or None, username or None, 0)
    except pywintypes.error as exc:
        code = exc.winerror
        if code == 1219:
            # Already connected under another account. Not a failure of ours: the
            # existing session may well be the right one, and the portal never
            # cancels somebody else's SMB connections.
            return True, f"{root}: bestehende Windows-Verbindung wird verwendet."
        if code == 1312:
            return True, f"{root}: bereits verbunden."
        return False, f"{root}: Windows-Fehler {code}."
    return True, f"{root}: verbunden."


def connect_status_share(path: str) -> tuple[bool, str]:
    """Connect one share, trying the bundled account before the stored one.

    The bundled password is tried first: this is the path a standard rollout
    takes, where nothing is stored yet and the release password is the one that
    works. If it is refused, a password somebody entered on this PC is tried,
    because that is the machine that was set up by hand.
    """
    from portal_app.services.reader_account import bundled_credentials

    bundled = bundled_credentials()
    stored = stored_reader_credentials()
    attempts = [item for item in (bundled, stored) if item is not None]
    if stored is not None and stored == bundled:
        attempts = [bundled]
    if not attempts:
        # No account at all: let Windows use whatever it already has for the
        # server, which is how a share set up through the dialog stays usable.
        return ensure_share_connection(path)
    result = (False, "")
    for username, password in attempts:
        result = ensure_share_connection(path, username, password)
        if result[0]:
            return result
    return result


def reconnect_status_shares(paths: dict[str, str]) -> dict[str, tuple[bool, str]]:
    """Re-establish every configured status share, keyed by machine ID.

    This is the step that was missing entirely: the fallback path and the saved
    Windows credentials both survived a restart, but nothing ever asked Windows
    to build the SMB session again, so the file fallback -- and with it the live
    status channel, whose pipe target is derived from the same server -- stayed
    dead until somebody re-ran the setup dialog by hand.
    """
    results: dict[str, tuple[bool, str]] = {}
    attempted: dict[str, tuple[bool, str]] = {}
    for workstation_id, path in paths.items():
        if not str(path).startswith("\\\\"):
            continue
        try:
            _, server, _ = parse_share_path(str(path))
        except ValueError as exc:
            results[workstation_id] = (False, str(exc))
            continue
        key = server.casefold()
        # One SMB session per server, not per machine: several machines may share
        # a server, and a second WNetAddConnection2 would only report 1219.
        if key not in attempted:
            attempted[key] = connect_status_share(str(path))
        results[workstation_id] = attempted[key]
    return results
