"""Windows token based authorization for the portal administration area."""

from __future__ import annotations

import csv
import io
import os
import subprocess
from dataclasses import dataclass


DEFAULT_ADMIN_GROUP = "RDP-Portal-Admins"


@dataclass(frozen=True)
class WindowsAdminAuthorization:
    authorized: bool
    group_name: str
    message: str


def configured_admin_group() -> str:
    """Return the centrally agreed group name, overridable for deployment."""
    return (os.environ.get("RDP_PORTAL_ADMIN_GROUP") or DEFAULT_ADMIN_GROUP).strip()


def test_password_fallback_allowed() -> bool:
    """Keep the local test password opt-out until AD authorization is ready."""
    configured = (os.environ.get("RDP_PORTAL_ALLOW_TEST_ADMIN_PASSWORD") or "true").strip().casefold()
    return configured not in {"0", "false", "no", "off"}


def check_windows_admin_authorization(group_name: str | None = None) -> WindowsAdminAuthorization:
    """Check direct Windows token groups without contacting or modifying AD."""
    group_name = (group_name or configured_admin_group()).strip()
    try:
        result = subprocess.run(
            ["whoami", "/groups", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=10,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return WindowsAdminAuthorization(False, group_name, "Windows-Gruppen konnten nicht geprüft werden.")
    if result.returncode != 0:
        return WindowsAdminAuthorization(False, group_name, "Windows-Gruppen konnten nicht geprüft werden.")
    expected = group_name.casefold()
    for row in csv.reader(io.StringIO(result.stdout)):
        if not row:
            continue
        token_group = row[0].strip()
        normalised = token_group.casefold()
        if normalised == expected or normalised.endswith("\\" + expected):
            return WindowsAdminAuthorization(
                True,
                group_name,
                f"Windows-Gruppe {token_group} bestätigt.",
            )
    return WindowsAdminAuthorization(
        False,
        group_name,
        f"Keine Mitgliedschaft in {group_name} im Windows-Token gefunden.",
    )


__all__ = [
    "DEFAULT_ADMIN_GROUP",
    "WindowsAdminAuthorization",
    "check_windows_admin_authorization",
    "configured_admin_group",
    "test_password_fallback_allowed",
]
