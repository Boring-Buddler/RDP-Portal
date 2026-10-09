"""Die erzeugten .rdp-Dateien mit ``rdpsign.exe`` signieren.

Unsigniert zeigt Windows vor jeder Verbindung "Unbekannter Herausgeber" und
gibt Zwischenablage, Laufwerke und Drucker erst frei, wenn jemand die Häkchen
setzt. Mit einer Signatur des eigenen Zertifikats steht dort der Herausgeber,
und mit dessen Fingerabdruck in der Richtlinie ``TrustedCertThumbprints``
entfällt der Dialog ganz -- nur für Dateien dieses Portals, nicht für eine
fremde .rdp-Datei aus einem Mailanhang.

Festlegungen, siehe ``docs/rdp-signatur-plan.md``:

* Der Fingerabdruck steht in ``HKLM\\SOFTWARE\\Kirschke\\RDPPortal``
  (``SigningThumbprint``), geschrieben von
  ``deployment/certificates/Install-RdpSigning.ps1``. Ohne Eintrag wird nicht
  signiert, und der Start verhält sich wie vorher.
* ``rdpsign /sha256`` erwartet trotz des Namens den **SHA-1**-Fingerabdruck
  (``Thumbprint``, 40 Zeichen); ``/sha256`` meint das Signaturverfahren. Mit
  dem SHA-256-Wert meldet es 0x80092004, "nicht gefunden" -- so geschehen
  mit 0.9.9. Ein solcher alter Eintrag wird abgelehnt und gemeldet.
* Das Zertifikat liegt im Computerspeicher (``LocalMachine\\My``).
* Die Signatur ist Komfort, kein Schutz, auf den das Portal angewiesen ist.
  Scheitert sie, wird die unveränderte Datei gestartet und das protokolliert.
* Nach dem Signieren wird die Datei nicht mehr verändert, sonst bricht die
  Signatur.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from shared.windows_tools import system32_tool

logger = logging.getLogger(__name__)

REGISTRY_KEY = r"SOFTWARE\Kirschke\RDPPortal"
REGISTRY_VALUE = "SigningThumbprint"

#: Signieren ist ein lokaler Dateivorgang. Dauert es länger, stimmt etwas nicht,
#: und die Verbindung soll trotzdem starten.
SIGN_TIMEOUT_SECONDS = 5.0

_SHA1 = re.compile(r"[0-9A-F]{40}")
_SHA256 = re.compile(r"[0-9A-F]{64}")


def configured_thumbprint() -> str | None:
    """Der SHA-1-Fingerabdruck aus der Registry, oder None ohne gültigen Eintrag."""
    try:
        import winreg
    except ImportError:  # kein Windows
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, REGISTRY_KEY) as key:
            value, kind = winreg.QueryValueEx(key, REGISTRY_VALUE)
    except OSError:
        return None
    return normalise_thumbprint(value if kind == winreg.REG_SZ else None)


def normalise_thumbprint(value: object) -> str | None:
    """Großbuchstaben ohne Leerzeichen; None, wenn es kein SHA-1-Fingerabdruck ist."""
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s", "", value).upper()
    if _SHA1.fullmatch(text):
        return text
    if _SHA256.fullmatch(text):
        logger.warning(
            "Signatur-Fingerabdruck ist ein SHA-256-Wert (Portal 0.9.9); rdpsign "
            "braucht den SHA-1-Fingerabdruck. Install-RdpSigning.ps1 erneut ausführen."
        )
    elif text:
        logger.warning("Signatur-Fingerabdruck in der Registry ist kein SHA-1-Wert")
    return None


def sign_rdp_file(path: str | Path, thumbprint: str | None = None) -> bool:
    """Die Datei signieren. Gibt zurück, ob sie danach signiert ist.

    Vor dem Signieren wird die Datei in UTF-16LE geschrieben, die übliche
    Kodierung von .rdp-Dateien, die mstsc und rdpsign beide sicher lesen. Bei
    jedem Fehler kommt der ursprüngliche Inhalt zurück, damit der Start genau
    so verläuft wie ohne Signatur.
    """
    thumbprint = configured_thumbprint() if thumbprint is None else normalise_thumbprint(thumbprint)
    if not thumbprint:
        return False
    try:
        tool = system32_tool("rdpsign.exe")
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("RDP-Datei nicht signiert: %s", exc)
        return False

    file = Path(path)
    original = file.read_bytes()
    try:
        file.write_text(original.decode("utf-8"), encoding="utf-16")
        result = subprocess.run(
            [tool, "/sha256", thumbprint, "/q", str(file)],
            shell=False,
            capture_output=True,
            timeout=SIGN_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        file.write_bytes(original)
        logger.warning("RDP-Datei nicht signiert: %s", exc)
        return False

    if result.returncode != 0 or not _carries_signature(file):
        file.write_bytes(original)
        detail = (result.stdout or b"").decode(errors="replace").strip()
        logger.warning(
            "RDP-Datei nicht signiert (rdpsign Rückgabewert %s): %s",
            result.returncode,
            detail or "keine Ausgabe",
        )
        return False
    logger.info("RDP-Datei signiert: %s", file.name)
    return True


def _carries_signature(file: Path) -> bool:
    """Ob rdpsign die Zeilen ``signscope`` und ``signature`` eingetragen hat."""
    try:
        raw = file.read_bytes()
    except OSError:
        return False
    for encoding in ("utf-16", "utf-8"):
        try:
            text = raw.decode(encoding)
        except UnicodeError:
            continue
        if "signscope:s:" in text and "signature:s:" in text:
            return True
    return False


__all__ = [
    "REGISTRY_KEY",
    "REGISTRY_VALUE",
    "configured_thumbprint",
    "normalise_thumbprint",
    "sign_rdp_file",
]
