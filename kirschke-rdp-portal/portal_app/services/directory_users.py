"""Best-effort discovery for selectable Windows domain accounts.

The portal never receives a password here.  The result is merely a cache for
the administrative RDP access dialog until an AD/Entra connector is configured.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DirectoryUserLookup:
    accounts: list[str]
    message: str


def discover_windows_domain_accounts() -> DirectoryUserLookup:
    """Read SAM account names from the current Windows domain if available."""
    domain = (os.environ.get("USERDOMAIN") or "").strip()
    if not domain:
        return DirectoryUserLookup([], "Keine Windows-Domäne erkannt.")
    try:
        result = subprocess.run(
            ["net", "user", "/domain"],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return DirectoryUserLookup([], "Windows-Domänenliste konnte nicht gelesen werden.")
    if result.returncode != 0:
        return DirectoryUserLookup([], "Windows-Domänenliste ist auf diesem Gerät nicht verfügbar.")

    accounts: list[str] = []
    in_account_block = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"-{3,}", stripped):
            in_account_block = True
            continue
        if not in_account_block:
            continue
        if not stripped or "command completed" in stripped.casefold() or "befehl" in stripped.casefold():
            break
        for token in stripped.split():
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", token):
                accounts.append(f"{domain}\\{token}")
    unique = sorted({account.casefold(): account for account in accounts}.values(), key=str.casefold)
    message = (
        f"{len(unique)} Benutzer aus der Windows-Domäne gefunden."
        if unique
        else "Keine Domänenbenutzer gefunden; bitte manuell hinzufügen."
    )
    return DirectoryUserLookup(unique, message)


__all__ = ["DirectoryUserLookup", "discover_windows_domain_accounts"]
