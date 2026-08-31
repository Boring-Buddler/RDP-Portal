"""Network-safe diagnostics for a planned RDP connection."""

from __future__ import annotations

import os
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from shared.schemas import RDPProfileSchema


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
    target, mode = profile.resolve_connection_target()
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    lines = [
        f"RDP-Verbindungsdiagnose · {timestamp}",
        f"Maschine: {profile.display_name}",
        f"Ziel: {target} ({mode.value})",
        f"RDP-Benutzer: {profile.username_hint or 'Beim Start abfragen'}",
        f"Webkonto / Entra: {'aktiv' if profile.effective_entra_sso_enabled() else 'aus'}",
        f"ServeridentitÃ¤ts-Ausnahme: {'aktiv' if profile.trust_unverified_server else 'aus'}",
        "Passwort: wird nicht protokolliert",
        "",
    ]

    addresses: list[str] = []
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(target, 3389, type=socket.SOCK_STREAM)})
        lines.append(f"NamensauflÃ¶sung: OK ({', '.join(addresses)})")
    except socket.gaierror as exc:
        lines.append(f"NamensauflÃ¶sung: FEHLER ({exc})")

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
        lines.append("TCP-Port 3389 (RDP): nicht geprÃ¼ft, weil die NamensauflÃ¶sung fehlgeschlagen ist")

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
            "- Ist Port 3389 nicht erreichbar, prÃ¼fen Sie Netzwerk, Firewall, VPN und den Remotedesktopdienst.",
            "- Ist Port 3389 erreichbar und Windows meldet trotzdem einen fehlgeschlagenen Anmeldeversuch,",
            "  prÃ¼fen Sie Benutzerformat, Berechtigung 'Remotedesktopbenutzer', DomÃ¤nen-/Entra-Zuordnung",
            "  sowie gespeicherte Windows-Anmeldedaten fÃ¼r dieses Ziel.",
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
            ["cmdkey", f"/list:{credential_target}"],
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


def clear_saved_rdp_credentials(target: str) -> tuple[bool, str]:
    """Remove exactly one RDP credential entry after the UI has confirmed it."""
    credential_target = f"TERMSRV/{target}"
    try:
        result = subprocess.run(
            ["cmdkey", f"/delete:{credential_target}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
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
                ["wevtutil", "qe", channel, "/rd:true", "/c:6", "/f:text"],
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


__all__ = ["RDPDiagnosticResult", "clear_saved_rdp_credentials", "run_rdp_diagnostics"]
