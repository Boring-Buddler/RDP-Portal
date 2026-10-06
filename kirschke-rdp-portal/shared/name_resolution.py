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
from collections.abc import Iterable
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
#: Wie lange ein noch nie gefragter Name auf seine erste Antwort wartet. Ein
#: funktionierendes DNS antwortet in Millisekunden; was länger braucht, wäre
#: ohnehin auf LOOKUP_TIMEOUT_SECONDS hinausgelaufen.
COLD_WAIT_SECONDS = 0.15

#: Laufende Nachschlagungen je Name; das Event wird gesetzt, wenn die Antwort
#: im Cache steht.
_in_flight: dict[str, threading.Event] = {}


def _is_literal_address(value: str) -> bool:
    """Whether the value is already an IP address and needs no lookup at all."""
    try:
        # A zone index (fe80::1%20) is part of the address for Windows but not
        # for the parser.
        ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return True


def unc_server_name(value: str | None) -> str:
    r"""Die Serverangabe für einen UNC-Pfad aus einer Rechnerkennung.

    Ein DNS-Name wird auf sein erstes Label gekürzt: Die Freigabe des Agenten
    heißt ``\\PC07\RDP-Status``, und der Domänensuffix steht dabei nur im Weg.

    Eine IP-Adresse muss dagegen unangetastet bleiben. Genau das ging schief:
    ``192.168.2.10`` wurde auf dieselbe Weise gekürzt, übrig blieb ``192``, und
    Windows beantwortete ``\\192\RDP-Status`` mit Fehler 67 -- der Netzwerkname
    wurde nicht gefunden, weil es diesen Server nicht gibt. Der Assistent meldete
    daraufhin "nicht eingerichtet" für eine Maschine, die über ihre IP durchaus
    erreichbar war.
    """
    name = (value or "").strip().strip("\\")
    if not name:
        return ""
    if _is_literal_address(name):
        return name
    return name.split(".", 1)[0]


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


def _start_lookup(name: str, key: str) -> threading.Event:
    """Look ``name`` up in the background. Caller holds ``_lock``.

    The returned event is set once the answer is in the cache.
    """
    done = threading.Event()
    _in_flight[key] = done

    def run() -> None:
        try:
            found = _lookup(name)
            ttl = POSITIVE_TTL_SECONDS if found else NEGATIVE_TTL_SECONDS
            with _lock:
                _cache[key] = (found, time.monotonic() + ttl)
        finally:
            with _lock:
                _in_flight.pop(key, None)
            done.set()

    threading.Thread(target=run, daemon=True, name="portal-name-lookup").start()
    return done


def resolvable(value: str | None, *, now: float | None = None) -> bool:
    """Whether ``value`` can be used as a connection target right now.

    An IP address is always usable. A name is looked up, and the answer is cached
    for a while. Anything empty is not usable.

    No caller waits for a slow DNS. The status poll asks from the Qt main thread,
    and every unresolvable name used to cost ``LOOKUP_TIMEOUT_SECONDS`` there --
    at startup once per name, one after the other, and afterwards each time its
    negative answer ran out. So:

    * An expired answer is still returned while a fresh lookup runs behind it.
    * The call that starts the first lookup for a name waits
      ``COLD_WAIT_SECONDS``, enough for a working DNS. Every further call while
      that lookup runs returns at once. Without an answer it counts as not
      resolvable for now, which
      is what a timed-out lookup always meant: the caller picks another
      identifier. The lookup itself carries on and fills the cache.
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
        if cached is not None:
            if cached[1] <= current and key not in _in_flight:
                _start_lookup(name, key)
            return cached[0]
        if key in _in_flight:
            # Schon gefragt -- vom Vorab-Nachschlagen oder einem früheren
            # Aufruf -- und noch keine Antwort: Dieser Name ist langsam, ein
            # weiteres Warten hielte nur den Aufrufer auf.
            return False
        done = _start_lookup(name, key)
    done.wait(COLD_WAIT_SECONDS)
    with _lock:
        cached = _cache.get(key)
    return cached[0] if cached is not None else False


def prefetch(values: Iterable[str | None]) -> None:
    """Start lookups for all ``values`` at once, without waiting for any.

    The portal calls this at startup with every name it is about to ask about,
    so the lookups run side by side instead of one after the other.
    """
    current = time.monotonic()
    with _lock:
        for value in values:
            name = (value or "").strip()
            if not name or _is_literal_address(name):
                continue
            key = name.casefold()
            cached = _cache.get(key)
            if key in _in_flight or (cached is not None and cached[1] > current):
                continue
            _start_lookup(name, key)


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
        _in_flight.clear()


__all__ = [
    "COLD_WAIT_SECONDS",
    "LOOKUP_TIMEOUT_SECONDS",
    "NEGATIVE_TTL_SECONDS",
    "POSITIVE_TTL_SECONDS",
    "clear_cache",
    "prefetch",
    "remember",
    "resolvable",
]
