"""Connect to an SMB status folder without exposing credentials to a shell."""
import os
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


#: Name der Statusfreigabe, die das Agent-Setup auf jedem Zielrechner anlegt.
AGENT_STATUS_SHARE = "RDP-Status"


def agent_status_share(host: str | None) -> str:
    r"""Die Standard-Statusfreigabe eines Rechners, etwa ``\\PC07\RDP-Status``.

    Leer, wenn sich aus der Angabe kein Servername bilden lässt.
    """
    from shared.name_resolution import unc_server_name

    server = unc_server_name(host)
    return rf"\\{server}\{AGENT_STATUS_SHARE}" if server else ""


#: Präfix der Einträge, unter denen das Portal sich ein Freigabekonto merkt.
SHARE_CREDENTIAL_PREFIX = "KirschkeRDPPortal:Freigabe:"

#: Kommentar der Server-Einträge, die das Portal bis 0.9.3 angelegt hat. Daran
#: sind sie von Einträgen zu unterscheiden, die jemand selbst gespeichert hat.
LEGACY_SERVER_CREDENTIAL_COMMENT = "RDP-Portal: SMB-Statusfreigabe"


def share_credential_target(server: str) -> str:
    """Der Name des Portal-Eintrags für die Freigaben eines Servers."""
    return SHARE_CREDENTIAL_PREFIX + server.strip().casefold()


def credential_payload(server: str, username: str, password: str) -> dict:
    r"""Das Freigabekonto als Portal-Eintrag, nicht als Anmeldung am Server.

    Bis 0.9.3 stand hier ein Windows-Eintrag vom Typ "Domänenkennwort" für den
    ganzen Server. Den nimmt Windows für *jede* Anmeldung an diesem Rechner --
    auch für Remotedesktop. mstsc meldete sich deshalb als ``PortalLeser`` an,
    egal welches Konto im Portal gewählt war, und weil das Agent-Setup diesem
    Konto die Remoteanmeldung verbietet, scheiterte jede Verbindung mit "nicht
    zur Remoteanmeldung autorisiert". Ein generischer Eintrag unter eigenem
    Namen wird von Windows nie von selbst benutzt; das Portal verbindet die
    Freigabe damit ausdrücklich, siehe :func:`connect_status_share`.
    """
    import win32cred

    return {
        "Type": win32cred.CRED_TYPE_GENERIC,
        "TargetName": share_credential_target(server),
        "UserName": username,
        # PyWin32's CredWrite wrapper performs UTF-16 conversion itself.
        # Passing encoded bytes raises TypeError before Windows is called.
        "CredentialBlob": password,
        "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        "Comment": f"RDP-Portal: Zugang zu den Freigaben auf {server}",
    }


def _reading_win32cred():
    """``win32cred`` samt dem Modul, das es beim Lesen von Einträgen nachlädt.

    ``CredRead`` und ``CredEnumerate`` wandeln den Zeitstempel ``LastWritten``
    in ein ``datetime`` und importieren dafür intern ``win32timezone``. Diesen
    Import sieht PyInstaller nicht; in der gebauten EXE brach der Start von
    0.9.4 deshalb mit "No module named 'win32timezone'" ab. Der ausdrückliche
    Import hier sorgt dafür, dass das Modul mitgepackt wird.
    """
    import win32cred
    import win32timezone  # noqa: F401 - siehe Docstring: nur fuer PyInstaller

    return win32cred


def stored_share_credentials(server: str) -> tuple[str, str] | None:
    """Das für diesen Server gemerkte Freigabekonto, oder ``None``."""
    import pywintypes

    win32cred = _reading_win32cred()
    try:
        entry = win32cred.CredRead(
            share_credential_target(server), win32cred.CRED_TYPE_GENERIC, 0
        )
    except pywintypes.error:
        return None
    return _credential_pair(entry)


def _credential_pair(entry: dict) -> tuple[str, str] | None:
    blob = entry.get("CredentialBlob")
    # CredRead hands back the raw UTF-16LE bytes CredWrite stored.
    password = (
        blob.decode("utf-16-le", errors="ignore")
        if isinstance(blob, bytes)
        else str(blob or "")
    )
    username = str(entry.get("UserName") or "").strip()
    return (username, password) if username and password else None


def verify_writable(directory: Path) -> None:
    """Durch einen echten Schreibversuch prüfen, ob dieser Ordner beschreibbar ist.

    Nötig für das gemeinsame Protokoll und das gemeinsame Inventar. Die
    Agentenfreigaben sind mit Leserecht
    eingerichtet, und dort *hineinzukommen* sagt nichts darüber, ob man
    hineinschreiben darf. Ohne diese Prüfung fiele das erst beim ersten Ereignis
    auf -- also dann, wenn niemand mehr an die Einstellung denkt.

    Die Probedatei wird wieder entfernt; bleibt sie liegen, ist das zwar
    unschön, aber kein Grund, die Einrichtung scheitern zu lassen.
    """
    probe = directory / f".rdp-portal-schreibtest-{os.getpid()}.tmp"
    try:
        probe.write_text("Schreibtest des RDP-Portals", encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"Der Ordner ist erreichbar, aber nicht beschreibbar ({exc.strerror or exc}). "
            "Für das gemeinsame Protokoll und Inventar braucht das verwendete Konto Schreibrecht; "
            "das Lesekonto der Agentenfreigaben genügt dafür nicht."
        ) from None
    try:
        probe.unlink()
    except OSError:
        pass


def connect_share(path: str, username: str, password: str, remember: bool, require_write: bool = False) -> tuple[str, str]:
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
    if require_write:
        verify_writable(Path(path))
    if remember:
        try:
            win32cred.CredWrite(credential_payload(server, username, password), 0)
        except (pywintypes.error, TypeError, ValueError) as exc:
            error = getattr(exc, "winerror", None)
            detail = f"Windows-Fehler {error}" if error is not None else type(exc).__name__
            raise ValueError(f"Freigabe erreichbar, aber die Zugangsdaten konnten nicht gespeichert werden ({detail}). "
                             "Ohne Speicherung erneut verbinden oder die Windows-Richtlinie prüfen.") from None
    if require_write:
        return path, f"Freigabe beschreibbar; {len(json_files)} JSON-Datei(en) lesbar."
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

    win32cred = _reading_win32cred()
    try:
        entry = win32cred.CredRead(READER_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except pywintypes.error:
        return None
    return _credential_pair(entry)


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
    """Connect one share, trying the bundled account before the stored ones.

    The bundled password is tried first: this is the path a standard rollout
    takes, where nothing is stored yet and the release password is the one that
    works. If it is refused, a password somebody entered on this PC is tried,
    because that is the machine that was set up by hand -- first the reader
    account, then whatever the setup dialog remembered for this very server.
    """
    from portal_app.services.reader_account import bundled_credentials

    try:
        _, server, _ = parse_share_path(path)
    except ValueError as exc:
        return False, str(exc)
    attempts: list[tuple[str, str]] = []
    # Zuletzt das für genau diesen Server gemerkte Konto: Es stammt aus dem
    # Einrichtungsdialog und ist der Weg für eine Freigabe, die nicht mit dem
    # Lesekonto erreichbar ist -- etwa ein Inventar unter eigenem Konto.
    for item in (bundled_credentials(), stored_reader_credentials(), stored_share_credentials(server)):
        if item is not None and item not in attempts:
            attempts.append(item)
    if not attempts:
        # No account at all: let Windows use whatever it already has for the
        # server, which is how a share set up through the dialog stays usable.
        return ensure_share_connection(path)
    result = (False, "")
    for username, password in attempts:
        result = ensure_share_connection(path, username, password)
        if result[0] or not _logon_refused(result[1]):
            # Ein ausgeschalteter Server lehnt nicht ab, er antwortet nicht. Ein
            # weiteres Konto kostete nur einen weiteren SMB-Timeout -- und das
            # beim Start, vor dem ersten Fenster.
            return result
    return result


#: Windows-Fehler, bei denen der Server erreichbar war und nur das Konto nicht
#: passte: Zugriff verweigert, falsches Kennwort, Anmeldefehler und die
#: Kontoeinschränkungen 1327 bis 1331, gesperrtes oder abgelaufenes Konto.
LOGON_REFUSED_CODES = frozenset({5, 86, 1326, 1327, 1328, 1329, 1330, 1331, 1907, 1909})


def _logon_refused(message: str) -> bool:
    """Ob eine Meldung von ensure_share_connection eine abgelehnte Anmeldung ist.

    Ohne erkennbaren Fehlercode gilt sie als abgelehnt: Dann wird wie bisher
    das nächste Konto versucht.
    """
    match = re.search(r"Windows-Fehler (\d+)", message)
    return match is None or int(match.group(1)) in LOGON_REFUSED_CODES


def retire_legacy_server_credentials() -> list[str]:
    r"""Die Server-Einträge entfernen, die das Portal früher selbst angelegt hat.

    Bis 0.9.3 merkte sich der Freigabedialog das Konto als Windows-Anmeldung
    für den ganzen Server, und Remotedesktop zu diesem Rechner meldete sich
    dann als ``PortalLeser`` an -- siehe :func:`credential_payload`.

    Entfernt wird nur, was zweifelsfrei vom Portal stammt (am Kommentar
    erkannt) *und* auf das Lesekonto lautet, und nur, wenn das Portal dieses
    Konto selbst kennt. Das Kennwort eines Domänen-Eintrags gibt Windows nicht
    heraus; ohne Ersatz wäre die Freigabe nach dem Entfernen nicht mehr zu
    erreichen. Gibt die Server zurück, deren Eintrag entfernt wurde.
    """
    import pywintypes

    win32cred = _reading_win32cred()
    reader = load_reader_credentials()
    if reader is None:
        return []
    reader_name = reader[0].rsplit("\\", 1)[-1].casefold()
    try:
        entries = win32cred.CredEnumerate(None, 0) or ()
    except pywintypes.error:
        return []
    retired: list[str] = []
    for entry in entries:
        if entry.get("Type") != win32cred.CRED_TYPE_DOMAIN_PASSWORD:
            continue
        if entry.get("Comment") != LEGACY_SERVER_CREDENTIAL_COMMENT:
            continue
        account = str(entry.get("UserName") or "").rsplit("\\", 1)[-1].casefold()
        if account != reader_name:
            continue
        target = str(entry.get("TargetName") or "")
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_DOMAIN_PASSWORD, 0)
        except pywintypes.error:
            continue
        retired.append(target)
    return retired


def setup_status_fallbacks(paths: dict[str, str]) -> dict[str, tuple[bool, str]]:
    """Die Statusfreigaben einrichten wie der Fallback-Dialog, für viele Maschinen.

    Verbunden wird mit dem Lesekonto, die JSON-Dateien werden probegelesen und
    das Konto für den Server gemerkt -- genau der Schritt, nach dem sich ein
    Agent in der Praxis meldete. Das bloße Wiederverbinden beim Start merkt
    sich nichts. Gelöscht wird nichts, auch kein hinterlegtes Lesekonto.

    Ist der Server schon unter einem anderen Konto verbunden oder lehnt er das
    Lesekonto ab, gilt wie beim Start :func:`connect_status_share`.
    """
    credentials = load_reader_credentials()
    results: dict[str, tuple[bool, str]] = {}
    attempted: dict[str, tuple[bool, str]] = {}
    for workstation_id, path in paths.items():
        try:
            _, server, _ = parse_share_path(str(path))
        except ValueError as exc:
            results[workstation_id] = (False, str(exc))
            continue
        key = server.casefold()
        if key not in attempted:
            attempted[key] = _setup_status_fallback(str(path), credentials)
        results[workstation_id] = attempted[key]
    return results


def _setup_status_fallback(path: str, credentials: tuple[str, str] | None) -> tuple[bool, str]:
    if credentials is None:
        return connect_status_share(path)
    try:
        _, message = connect_share(path, *credentials, remember=True)
    except ValueError as exc:
        code = re.search(r"Fehler (\d+)", str(exc))
        # Nur dann ein zweiter Versuch: Ein ausgeschalteter Rechner kostete
        # sonst einen zweiten SMB-Timeout.
        if "anderen Konto" in str(exc) or (code and int(code.group(1)) in LOGON_REFUSED_CODES):
            connected = connect_status_share(path)
            if connected[0]:
                return connected
        return False, f"{path}: {exc}"
    return True, f"{path}: {message}"


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
