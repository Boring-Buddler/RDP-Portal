"""Resolve the initial portal identity from the signed-in Windows account."""

from __future__ import annotations

import subprocess

from portal_app.models.user import MockUser, UserRole


def detect_initial_user(fallback: MockUser | None = None) -> MockUser:
    """Return a local portal user based on ``whoami`` or a safe fallback."""
    fallback = fallback or MockUser.create_user()
    try:
        result = subprocess.run(
            ["whoami"],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return fallback

    identity = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    domain, separator, username = identity.partition("\\")
    if result.returncode != 0 or not separator or not domain or not username:
        return fallback
    domain = domain.strip()
    username = username.strip()
    if not domain or not username:
        return fallback
    return MockUser(
        object_id=f"local-{domain.lower()}-{username.lower()}",
        upn=identity,
        display_name=username,
        email=None,
        role=UserRole.USER,
        rdp_username=username,
        rdp_domain=domain,
    )


__all__ = ["detect_initial_user"]
