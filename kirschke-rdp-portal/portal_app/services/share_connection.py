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
