"""Find the agents on this network and say who they are.

The portal used to have no way to answer "which agents can I see at all?".  Agent
assignment read the snapshot folder of the very machine being assigned, so the
list was empty exactly when it was needed -- before a fallback share existed.
This module answers the question from the network instead.

Two facts make that possible without any credentials:

* The agent's named pipe exists on every machine that runs one.  Opening it is
  restricted by SDDL to SYSTEM, local administrators and ``PortalLeser``, but
  ``WaitNamedPipe`` reports whether the pipe *is there* before access is checked,
  and ``CreateFile`` then distinguishes "access denied" (an agent, no rights yet)
  from "not found" (no agent).  So an unauthenticated sweep can find agents; it
  just cannot read them.
* With the reader credentials, the very same ``STATUS/1`` request the dashboard
  already uses returns the agent's own machine ID, host name and version.  That
  is the identification step, and it reuses the protocol rather than adding one.

A sweep is deliberately explicit: it is started by a person from the wizard or
the settings page, never on a timer.  Probing every address of a /24 every few
seconds would be a steady stream of connection attempts against machines that
have nothing to do with the portal.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from portal_app.services.machine_discovery import discover_remote_machine
from portal_app.services.site_mapping import site_for_address
from shared.agent_snapshot import AgentSnapshot
from shared.status_pipe import PIPE_NAME, request_snapshot

#: How long one address may take to say whether a pipe is there. A machine that
#: is up answers in milliseconds; this budget is for the ones that are not, and
#: it is multiplied by the number of addresses divided by the worker count.
PROBE_TIMEOUT_MS = 700

#: Largest range a single sweep will walk. A /24 is 254 hosts, which is the size
#: of both office networks. Anything larger is refused rather than silently
#: truncated, so nobody believes a /16 was fully scanned.
MAX_SWEEP_ADDRESSES = 1024

#: Windows error codes that mean "the pipe is there, you may not open it".
#: ERROR_ACCESS_DENIED, and the two that appear when the SMB session itself is
#: rejected before the pipe is ever reached.
_AGENT_PRESENT_ERRORS = frozenset({5, 1326, 1327, 1331, 1385, 1396, 1909})

#: "No agent here" -- the host answered SMB but has no such pipe, or did not
#: answer at all.
_NO_AGENT_ERRORS = frozenset({2, 3, 51, 53, 64, 67, 121, 231, 1231, 1232})


@dataclass(frozen=True)
class AgentProbe:
    """What one address turned out to be."""

    target: str
    #: True when a Kirschke agent answered or refused us at this address.
    agent_present: bool = False
    #: Filled in only when the reader credentials were accepted.
    snapshot: AgentSnapshot | None = None
    #: Why identification did not happen, in words fit for the interface.
    message: str = ""

    @property
    def identified(self) -> bool:
        return self.snapshot is not None

    @property
    def workstation_id(self) -> str:
        return self.snapshot.workstation_id.strip() if self.snapshot else ""

    @property
    def hostname(self) -> str:
        return self.snapshot.hostname.strip() if self.snapshot else ""

    @property
    def agent_version(self) -> str:
        return (self.snapshot.agent_version or "").strip() if self.snapshot else ""

    def label(self) -> str:
        """One line naming this agent the way a person would recognise it."""
        if not self.identified:
            return f"{self.target} · Agent gefunden, noch nicht identifiziert"
        return f"{self.hostname or self.workstation_id} · {self.target} · Agent {self.agent_version or '?'}"


def pipe_present(target: str, timeout_ms: int = PROBE_TIMEOUT_MS) -> bool:
    """Whether the agent's pipe exists on ``target``, without opening it.

    Access rights are not consulted here at all: ``WaitNamedPipe`` answers for
    the pipe's existence, which is the whole point -- a machine may run an agent
    the portal is not yet allowed to read.
    """
    import pywintypes
    import win32pipe

    if not _is_pipe_target(target):
        return False
    try:
        win32pipe.WaitNamedPipe(rf"\\{target}\pipe\{PIPE_NAME}", max(1, timeout_ms))
    except pywintypes.error as exc:
        # ERROR_SEM_TIMEOUT (121) here means "no instance became free", which
        # only happens when the pipe exists and is busy.
        return exc.winerror in _AGENT_PRESENT_ERRORS or exc.winerror == 121
    return True


def probe_agent(target: str, timeout_ms: int = PROBE_TIMEOUT_MS) -> AgentProbe:
    """Ask one address whether it runs an agent, and who it is.

    Never raises for an unreachable or hostile target: the result says what was
    learned, because a sweep must not stop at the first machine that is off.
    """
    target = (target or "").strip()
    if not _is_pipe_target(target):
        return AgentProbe(target, message="Kein gültiger Hostname und keine IP-Adresse.")
    if not pipe_present(target, timeout_ms):
        return AgentProbe(target, message="Kein Agent erreichbar.")
    try:
        snapshot, _ = request_snapshot(target)
    except Exception as exc:  # noqa: BLE001 - every failure is a probe result
        code = getattr(exc, "winerror", None)
        if code is None and exc.args and isinstance(exc.args[0], int):
            code = exc.args[0]
        if code in _NO_AGENT_ERRORS:
            return AgentProbe(target, message="Kein Agent erreichbar.")
        return AgentProbe(
            target,
            agent_present=True,
            message=(
                "Agent gefunden, aber nicht lesbar. Zugangsdaten des Lesekontos "
                f"in den Einstellungen hinterlegen ({code or type(exc).__name__})."
            ),
        )
    return AgentProbe(target, agent_present=True, snapshot=snapshot, message="Agent hat geantwortet.")


def probe_prefill(probe: AgentProbe) -> dict[str, str]:
    """Turn an identified agent into values the machine form understands.

    The agent states its own host name, which beats reverse DNS; everything else
    still comes from the existing discovery so this stays one code path.
    """
    discovery = discover_remote_machine(probe.target)
    prefill = discovery.as_prefill()
    if probe.hostname:
        prefill["hostname"] = probe.hostname
        prefill["display_name"] = probe.hostname
    if not prefill.get("ip_address") and _is_address(probe.target):
        prefill["ip_address"] = probe.target
    prefill["site"] = site_for_address(prefill.get("ip_address") or probe.target)
    return prefill


def sweep_addresses(networks: Iterable[str]) -> list[str]:
    """Expand CIDR ranges and single addresses into the hosts to probe.

    Duplicates are removed and order is kept, so a list of overlapping ranges
    costs one probe per address rather than one per mention.
    """
    result: list[str] = []
    seen: set[str] = set()
    for entry in networks:
        for address in _expand(entry):
            if address not in seen:
                seen.add(address)
                result.append(address)
        if len(result) > MAX_SWEEP_ADDRESSES:
            raise ValueError(
                f"Der Suchbereich umfasst mehr als {MAX_SWEEP_ADDRESSES} Adressen. "
                "Bitte kleinere Bereiche angeben, etwa 192.168.2.0/24."
            )
    return result


def local_sweep_networks() -> list[str]:
    """The ranges worth offering by default: this PC's own /24 and both offices.

    The local network comes first because it is the one that certainly exists;
    the two office ranges follow so a portal at one site can still find the other
    over the VPN without anybody typing a CIDR.
    """
    from portal_app.services.machine_discovery import discover_local_machine
    from portal_app.services.site_mapping import SITE_NETWORKS

    result: list[str] = []
    local = discover_local_machine()
    if local.ip_address:
        try:
            network = ipaddress.ip_network(f"{local.ip_address}/24", strict=False)
            result.append(str(network))
        except ValueError:
            pass
    for network, _ in SITE_NETWORKS:
        if str(network) not in result:
            result.append(str(network))
    return result


def _expand(entry: str) -> Iterator[str]:
    value = (entry or "").strip()
    if not value:
        return
    if "/" in value:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return
        # .hosts() already drops network and broadcast address for IPv4.
        for host in network.hosts():
            yield str(host)
        return
    yield value


def _is_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def _is_pipe_target(value: str) -> bool:
    """Mirror the restriction ``shared.status_pipe`` puts on a pipe target."""
    return bool(value) and bool(re.fullmatch(r"[A-Za-z0-9_.-]+", value)) and value not in (".", "..")


class _ProbeSignals(QObject):
    finished = Signal(object)


class _ProbeTask(QRunnable):
    def __init__(self, target: str, timeout_ms: int) -> None:
        super().__init__()
        self.target = target
        self.timeout_ms = timeout_ms
        self.signals = _ProbeSignals()

    @Slot()
    def run(self) -> None:
        try:
            probe = probe_agent(self.target, self.timeout_ms)
        except Exception as exc:  # noqa: BLE001 - a sweep never dies on one host
            probe = AgentProbe(self.target, message=f"Prüfung fehlgeschlagen ({type(exc).__name__}).")
        self.signals.finished.emit(probe)


class AgentScanner(QObject):
    """Probe many addresses in parallel and report agents as they are found.

    Results arrive one at a time so the list fills while the sweep is still
    running -- on a quiet /24 most of the wall time is spent waiting for the
    addresses where nothing answers.
    """

    #: One agent was found. Carries an AgentProbe.
    found = Signal(object)
    #: Addresses done, addresses total.
    progress = Signal(int, int)
    #: The sweep ended. Carries how many agents were found.
    finished = Signal(int)

    def __init__(self, max_parallel: int = 16, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(1, max_parallel))
        self._total = 0
        self._done = 0
        self._found = 0
        self._running = False
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, targets: list[str], timeout_ms: int = PROBE_TIMEOUT_MS) -> int:
        """Begin a sweep. Returns how many addresses will be probed."""
        if self._running or not targets:
            return 0
        self._running = True
        self._cancelled = False
        self._total = len(targets)
        self._done = 0
        self._found = 0
        for target in targets:
            task = _ProbeTask(target, timeout_ms)
            task.signals.finished.connect(self._on_probe)
            self.pool.start(task)
        return self._total

    def cancel(self) -> None:
        """Stop starting new probes; the ones already running are let finish."""
        if not self._running:
            return
        self._cancelled = True
        self.pool.clear()

    @Slot(object)
    def _on_probe(self, probe: object) -> None:
        self._done += 1
        if isinstance(probe, AgentProbe) and probe.agent_present and not self._cancelled:
            self._found += 1
            self.found.emit(probe)
        self.progress.emit(self._done, self._total)
        if self._done >= self._total or (self._cancelled and self.pool.activeThreadCount() <= 1):
            if self._running:
                self._running = False
                self.finished.emit(self._found)

    def stop(self) -> None:
        self._cancelled = True
        self._running = False
        self.pool.clear()
        self.pool.waitForDone(3000)


__all__ = [
    "MAX_SWEEP_ADDRESSES",
    "PROBE_TIMEOUT_MS",
    "AgentProbe",
    "AgentScanner",
    "local_sweep_networks",
    "pipe_present",
    "probe_agent",
    "probe_prefill",
    "sweep_addresses",
]
