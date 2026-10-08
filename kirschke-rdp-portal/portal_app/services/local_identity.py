"""Resolve the initial portal identity from the signed-in Windows account."""

from __future__ import annotations

import os
import re
import subprocess

from portal_app.models.user import MockUser, UserRole
from shared.windows_tools import system32_tool


def _whoami(*arguments: str) -> str:
    """Return the first output line of ``whoami``, or ``""`` when it failed."""
    try:
        result = subprocess.run(
            [system32_tool("whoami.exe"), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    return result.stdout.strip().splitlines()[0].strip()


def local_machine_names() -> set[str]:
    """The names and addresses under which this PC reaches another machine.

    An agent reports the RDP client of a session as a computer name or as an
    address, depending on how the connection was made. Comparing against all of
    them is what lets the portal recognise "this session was opened from here".
    """
    import socket

    names: set[str] = set()
    for value in (os.environ.get("COMPUTERNAME"), socket.gethostname()):
        name = (value or "").strip()
        if name:
            names.add(name.casefold())
            names.add(name.split(".", 1)[0].casefold())
    try:
        for entry in socket.getaddrinfo(socket.gethostname(), None):
            names.add(str(entry[4][0]).split("%", 1)[0].casefold())
    except OSError:
        pass
    return {name for name in names if name}


#: Wie lange local_client_names ein Ergebnis wiederverwendet. Die Namen ändern
#: sich praktisch nie, eine Adresse schon -- etwa beim Wechsel ins VPN.
CLIENT_NAMES_TTL_SECONDS = 300.0

_client_names_cache: tuple[float, frozenset[str]] | None = None


def local_client_names() -> frozenset[str]:
    """``local_machine_names`` in der Form, in der sie mit Sitzungen verglichen werden.

    Gepuffert, weil die Frage bei jedem Zeichnen einer Karte gestellt wird und
    ``getaddrinfo`` dabei nicht jedes Mal laufen soll.
    """
    import time

    from shared.session_identity import host_aliases

    global _client_names_cache
    now = time.monotonic()
    if _client_names_cache is not None and now - _client_names_cache[0] < CLIENT_NAMES_TTL_SECONDS:
        return _client_names_cache[1]
    names = frozenset(alias for name in local_machine_names() for alias in host_aliases(name))
    _client_names_cache = (now, names)
    return names


def _detect_identity() -> tuple[str, str | None]:
    r"""Return the ``DOMAIN\user`` name of this process and its SID when available.

    ``whoami /user`` reports both at once, and its SID is the form the agent also
    reports for a session -- so the portal can compare SID to SID instead of
    matching display names that Entra spells differently on every machine.  When
    the CSV form is unavailable the plain name still works; the comparison then
    degrades to a name match, which the UI marks as unverified.
    """
    fields = re.findall(r'"([^"]*)"', _whoami("/user", "/fo", "csv", "/nh"))
    if len(fields) >= 2 and fields[0] and fields[1].upper().startswith("S-1-"):
        return fields[0].strip(), fields[1].strip()
    return _whoami(), None


def detect_initial_user(fallback: MockUser | None = None) -> MockUser:
    """Return a local portal user based on ``whoami`` or a safe fallback."""
    fallback = fallback or MockUser.create_user()
    identity, sid = _detect_identity()
    domain, separator, username = identity.partition("\\")
    if not separator or not domain or not username:
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
        windows_identity=identity,
        windows_sid=sid,
    )


__all__ = ["detect_initial_user"]
