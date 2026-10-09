"""Network-safe diagnostics for a planned RDP connection."""

from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shared.schemas import RDPProfileSchema
from shared.windows_tools import system32_tool


@dataclass(frozen=True)
class RDPDiagnosticResult:
    """Outcome of checks that can be performed before mstsc authenticates."""

    target: str
    port_open: bool | None
    saved_credentials_present: bool | None
    report: str
    log_path: Path


def run_rdp_diagnostics(profile: RDPProfileSchema, timeout_seconds: float = 3.0) -> RDPDiagnosticResult:
    """Check name resolution and TCP/3389 without sending credentials.

    The report intentionally records no password and never attempts a login.  A
    reachable RDP service is useful evidence, but does not prove that the user
    account is allowed to sign in.
    """
    from portal_app.rdp.signing import configured_thumbprint

    target, mode = profile.resolve_connection_target()
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        f"RDP-Verbindungsdiagnose · {timestamp}",
        f"Maschine: {profile.display_name}",
        f"Ziel: {target} ({mode.value})",
        f"RDP-Benutzer: {profile.effective_rdp_username() or 'Beim Start abfragen'}",
        f"Webkonto / Entra: {'aktiv' if profile.effective_entra_sso_enabled() else 'aus'}",
        f"Serveridentitäts-Ausnahme: {'aktiv' if profile.trust_unverified_server else 'aus'}",
        f"RDP-Signatur: {'eingerichtet' if configured_thumbprint() else 'nicht eingerichtet'}",
        "Passwort: wird nicht protokolliert",
        "",
    ]

    addresses: list[str] = []
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(target, 3389, type=socket.SOCK_STREAM)})
        lines.append(f"Namensauflösung: OK ({', '.join(addresses)})")
    except socket.gaierror as exc:
        lines.append(f"Namensauflösung: FEHLER ({exc})")

    port_open: bool | None = None
    if addresses:
        try:
            with socket.create_connection((target, 3389), timeout=timeout_seconds):
                port_open = True
            lines.append("TCP-Port 3389 (RDP): ERREICHBAR")
        except OSError as exc:
            port_open = False
            lines.append(f"TCP-Port 3389 (RDP): NICHT ERREICHBAR ({exc})")
    else:
        lines.append("TCP-Port 3389 (RDP): nicht geprüft, weil die Namensauflösung fehlgeschlagen ist")

    lines.extend(("", "Letzte lokale Windows-RDP-Clientereignisse:"))
    saved_credentials_present = _has_saved_rdp_credentials(target)
    credential_status = (
        "VORHANDEN" if saved_credentials_present else "nicht vorhanden"
        if saved_credentials_present is not None else "nicht pr\u00fcfbar"
    )
    lines.append(f"Gespeicherte Windows-Anmeldedaten f\u00fcr dieses Ziel: {credential_status}")
    lines.append("Hinweis: Gespeicherte Anmeldedaten k\u00f6nnen einen alten Benutzer vorausw\u00e4hlen.")

    event_output = _recent_rdp_client_events()
    lines.append(event_output or "Keine lesbaren Ereignisse gefunden.")

    lines.extend(
        (
            "",
            "Einordnung:",
            "- Ist Port 3389 nicht erreichbar, prüfen Sie Netzwerk, Firewall, VPN und den Remotedesktopdienst.",
            "- Ist Port 3389 erreichbar und Windows meldet trotzdem einen fehlgeschlagenen Anmeldeversuch,",
            "  prüfen Sie Benutzerformat, Gruppenmitgliedschaft, Domänen-/Entra-Zuordnung",
            "  sowie gespeicherte Windows-Anmeldedaten für dieses Ziel.",
            "- Die Gruppe heißt je nach Systemsprache 'Remotedesktopbenutzer' oder 'Remote Desktop Users';",
            "  sprachunabhängig ist nur ihre SID S-1-5-32-555:",
            "      $name = (Get-LocalGroup -SID 'S-1-5-32-555').Name",
            "- Meldet der Zielrechner 'Benutzerkonto nicht zur Remoteanmeldung autorisiert' (0x3 / 0x9),",
            "  prüfen Sie am Ziel das tatsächlich verwendete Konto und dessen SID sowie die",
            "  wirksamen Rechte für die Remotedesktopanmeldung. Die Meldung allein bestätigt",
            "  nicht, dass Windows das im Portal ausgewählte Konto verwendet hat.",
            "- Für Entra ohne Webanmeldung sind UPN und AzureAD\\<UPN> unterstützte Kontonamen.",
            "  Webanmeldung verwendet den UPN und benötigt einen Hostnamen statt einer IP-Adresse.",
        )
    )
    report = "\n".join(lines)
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
    log_path = Path(local_data) / "KirschkeRDPPortal" / "rdp-debug.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(report + "\n\n" + ("-" * 72) + "\n\n")
    return RDPDiagnosticResult(
        target=target,
        port_open=port_open,
        saved_credentials_present=saved_credentials_present,
        report=report,
        log_path=log_path,
    )


def _has_saved_rdp_credentials(target: str) -> bool | None:
    """Check for a matching Windows Credential Manager entry without reading it."""
    credential_target = f"TERMSRV/{target}"
    try:
        result = subprocess.run(
            [system32_tool("cmdkey.exe"), f"/list:{credential_target}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=4,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return credential_target.casefold() in result.stdout.casefold()


#: Wie cmdkey die Zeile mit dem Kontonamen beschriftet, je nach Systemsprache.
_CMDKEY_USER_LABELS = ("benutzer", "user")


def _decode_console_output(raw: bytes) -> str:
    """cmdkey schreibt je nach Umgebung UTF-8 oder in der OEM-Codepage."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        codec = "oem" if os.name == "nt" else "cp850"
        return raw.decode(codec, errors="replace")


def saved_rdp_credential_user(target: str) -> str | None:
    """Das Konto, für das Windows Anmeldedaten zu diesem RDP-Ziel gespeichert hat.

    Liegt ein solcher Eintrag vor, meldet mstsc mit ihm an und nicht mit dem
    Konto aus der .rdp-Datei. Wer im Portal ein anderes Konto wählt, landet
    sonst ohne Hinweis unter dem gespeicherten. Gelesen wird nur der
    Kontoname; das Kennwort gibt cmdkey nicht heraus.

    ``None``, wenn kein Eintrag vorliegt oder er sich nicht lesen lässt.
    """
    credential_target = f"TERMSRV/{target}"
    try:
        result = subprocess.run(
            [system32_tool("cmdkey.exe"), f"/list:{credential_target}"],
            capture_output=True,
            timeout=4,
            check=False,
            # Läuft bei jedem Verbinden; ohne das blitzte ein Konsolenfenster auf.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return credential_user_from_cmdkey(_decode_console_output(result.stdout), target)


def credential_user_from_cmdkey(output: str, target: str) -> str | None:
    """Den Kontonamen zum Eintrag ``TERMSRV/<target>`` aus der cmdkey-Liste lesen."""
    if f"TERMSRV/{target}".casefold() not in output.casefold():
        return None
    for line in output.splitlines():
        label, separator, value = line.strip().partition(":")
        if separator and label.strip().casefold() in _CMDKEY_USER_LABELS:
            return value.strip() or None
    return None


def saved_server_credential_user(target: str) -> str | None:
    r"""Das Konto eines Windows-Eintrags für den ganzen Server ``target``.

    Gemeint ist ``Domain:target=<target>`` -- nicht ``TERMSRV/<target>``. Auch
    so einen Eintrag nimmt mstsc und übergeht damit die .rdp-Datei. Er entsteht,
    wenn jemand beim Verbinden einer Dateifreigabe "Anmeldedaten speichern"
    ankreuzt; das Portal selbst hat ihn bis 0.9.3 für jede Statusfreigabe
    angelegt, und zwar für ``PortalLeser``.
    """
    try:
        result = subprocess.run(
            [system32_tool("cmdkey.exe"), f"/list:{target}"],
            capture_output=True,
            timeout=4,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return server_credential_user_from_cmdkey(_decode_console_output(result.stdout), target)


def server_credential_user_from_cmdkey(output: str, target: str) -> str | None:
    """Den Kontonamen zu ``Domain:target=<target>`` aus der cmdkey-Liste lesen.

    Blockweise und mit genauem Vergleich: ``TERMSRV/<target>`` oder ein
    anderer Server mit ähnlichem Namen gehören nicht dazu. ``Domain:target``
    schreibt cmdkey in jeder Systemsprache gleich.
    """
    wanted = target.strip().casefold()
    current = False
    for line in output.splitlines():
        text = line.strip()
        marker = text.casefold().find("domain:target=")
        if marker >= 0:
            current = text[marker + len("domain:target="):].strip().casefold() == wanted
            continue
        if "target=" in text.casefold():
            current = False
            continue
        label, separator, value = text.partition(":")
        if current and separator and label.strip().casefold() in _CMDKEY_USER_LABELS:
            return value.strip() or None
    return None


def clear_saved_server_credentials(target: str) -> tuple[bool, str]:
    """Den Windows-Eintrag für den ganzen Server ``target`` nach Bestätigung entfernen."""
    try:
        result = subprocess.run(
            [system32_tool("cmdkey.exe"), f"/delete:{target}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Die Windows-Anmeldeinformationsverwaltung konnte nicht gestartet werden: {exc}"
    if result.returncode == 0:
        return True, f"Gespeicherte Anmeldedaten für {target} wurden entfernt."
    detail = (result.stderr or result.stdout).strip()
    return False, detail or f"Windows konnte den Eintrag {target} nicht entfernen."


def clear_saved_rdp_credentials(target: str) -> tuple[bool, str]:
    """Remove exactly one RDP credential entry after the UI has confirmed it."""
    credential_target = f"TERMSRV/{target}"
    try:
        result = subprocess.run(
            [system32_tool("cmdkey.exe"), f"/delete:{credential_target}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Die Windows-Anmeldeinformationsverwaltung konnte nicht gestartet werden: {exc}"
    if result.returncode == 0:
        return True, f"Gespeicherte Anmeldedaten für {credential_target} wurden entfernt."
    detail = (result.stderr or result.stdout).strip()
    return False, detail or f"Windows konnte den Eintrag {credential_target} nicht entfernen."


def _recent_rdp_client_events() -> str:
    """Read recent client-side RDP events without elevating privileges.

    Windows versions expose one or both of these operational logs.  Failure to
    read them is non-fatal: the network checks above remain valid.
    """
    outputs: list[str] = []
    for channel in (
        "Microsoft-Windows-TerminalServices-ClientActiveXCore/Operational",
        "Microsoft-Windows-TerminalServices-RDPClient/Operational",
    ):
        try:
            result = subprocess.run(
                [system32_tool("wevtutil.exe"), "qe", channel, "/rd:true", "/c:6", "/f:text"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            # Bound the report so that a noisy event channel cannot make the
            # dialog or local debug file unwieldy.
            outputs.append(f"[{channel}]\n{result.stdout.strip()[-6000:]}")
    return "\n\n".join(outputs)


__all__ = [
    "RDPDiagnosticResult",
    "clear_saved_rdp_credentials",
    "clear_saved_server_credentials",
    "credential_user_from_cmdkey",
    "run_rdp_diagnostics",
    "saved_rdp_credential_user",
    "saved_server_credential_user",
    "server_credential_user_from_cmdkey",
]
