"""Is this host identifier usable right now?

A machine can be reachable under several identifiers that are not equally
usable. Across two sites the short Windows name is the common failure: NetBIOS
and LLMNR are link-local, a router does not forward them, and without a DNS
suffix ``PC07`` resolves in its own segment and nowhere else. The IP address of
the very same machine works fine.

The portal used to pick the first *configured* identifier and hand it to
``mstsc``, which then reported that it "cannot find the computer PC07" -- while a
manual connection to the IP worked. This module is what lets the automatic
choice skip an identifier that cannot be resolved instead of failing on it.

Two properties matter here and shape the implementation:

* **It must not block the interface.** The lookup runs on a daemon thread with a
  hard time limit, the same approach the agent uses for its own name matching. A
  slow or absent DNS costs one wrong-looking card, never a frozen window.
* **It must not ask again for every card refresh.** The status poll runs every
  few seconds; an uncached lookup per machine per cycle would be a steady stream
  of DNS traffic. Answers are therefore cached, positive ones longer than
  negative ones, so a machine that comes online is picked up reasonably soon
  while a name that works stays cheap.
"""

from __future__ import annotations

import socket
import threading
import time
from ipaddress import ip_address

#: How long a successful lookup is trusted. A name that resolves rarely stops.
POSITIVE_TTL_SECONDS = 300.0

#: How long a failure is trusted. Shorter, so a machine that has just come up, or
#: a DNS server that was briefly unavailable, is not written off for minutes.
NEGATIVE_TTL_SECONDS = 30.0

#: Hard limit for one lookup. Beyond this the answer counts as "not resolvable";
#: the caller then uses another identifier, which is the better outcome anyway.
LOOKUP_TIMEOUT_SECONDS = 2.0

_cache: dict[str, tuple[bool, float]] = {}
_lock = threading.Lock()


def _is_literal_address(value: str) -> bool:
    """Whether the value is already an IP address and needs no lookup at all."""
    try:
        # A zone index (fe80::1%20) is part of the address for Windows but not
        # for the parser.
        ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return True


def _lookup(name: str) -> bool:
    """One bounded name lookup, on a thread that may outlive the answer."""
    result: list[bool] = [False]

    def run() -> None:
        try:
            socket.getaddrinfo(name, None)
        except OSError:
            return
        result[0] = True

    worker = threading.Thread(target=run, daemon=True, name="portal-name-lookup")
    worker.start()
    worker.join(LOOKUP_TIMEOUT_SECONDS)
    # A single assignment, so reading it while the thread still runs is safe.
    return result[0]


def resolvable(value: str | None, *, now: float | None = None) -> bool:
    """Whether ``value`` can be used as a connection target right now.

    An IP address is always usable. A name is looked up, and the answer is cached
    for a while. Anything empty is not usable.
    """
    name = (value or "").strip()
    if not name:
        return False
    if _is_literal_address(name):
        return True
    key = name.casefold()
    current = time.monotonic() if now is None else now
    with _lock:
        cached = _cache.get(key)
        if cached is not None and cached[1] > current:
            return cached[0]
    found = _lookup(name)
    ttl = POSITIVE_TTL_SECONDS if found else NEGATIVE_TTL_SECONDS
    with _lock:
        _cache[key] = (found, current + ttl)
    return found


def remember(value: str, found: bool, *, now: float | None = None) -> None:
    """Seed the cache, so a caller that already knows need not look up again."""
    name = (value or "").strip()
    if not name or _is_literal_address(name):
        return
    current = time.monotonic() if now is None else now
    ttl = POSITIVE_TTL_SECONDS if found else NEGATIVE_TTL_SECONDS
    with _lock:
        _cache[name.casefold()] = (found, current + ttl)


def clear_cache() -> None:
    """Forget every answer. For tests, and for a deliberate refresh."""
    with _lock:
        _cache.clear()


__all__ = [
    "LOOKUP_TIMEOUT_SECONDS",
    "NEGATIVE_TTL_SECONDS",
    "POSITIVE_TTL_SECONDS",
    "clear_cache",
    "remember",
    "resolvable",
]
