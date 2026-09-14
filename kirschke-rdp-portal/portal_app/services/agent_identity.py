"""One rule for "is this the agent of this machine?".

The status channel and the logoff path both have to answer this, and they used to
answer it differently: the status channel accepted a matching *hostname* when no
agent had been assigned explicitly, the logoff path compared only the machine ID.
A machine whose portal ID differs from its hostname -- the normal case, because
portal IDs are generated and hostnames are not -- therefore showed a healthy live
status and then refused every logoff with a mismatch no one could see.

Both now ask here.  The rule is deliberately the weaker of the two, not the
stricter one: whatever evidence is good enough to display an agent's session data
as this machine's is good enough to act on that same session.  An explicit
assignment always wins, because that is a person stating the mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address


def name_values(value: str | None) -> set[str]:
    """Every spelling one host name or address should be recognised by."""
    text = (value or "").strip().rstrip(".").casefold()
    if not text:
        return set()
    try:
        return {str(ip_address(text))}
    except ValueError:
        pass
    return {text, text.split(".", 1)[0]}


def machine_hostnames(workstation) -> set[str]:
    """Every spelling a machine's own host name and FQDN should be recognised by."""
    return name_values(workstation.hostname) | name_values(workstation.fqdn)


@dataclass(frozen=True)
class AgentMatch:
    """Whether an agent belongs to a machine, and why it was decided that way."""

    matches: bool
    reason: str

    def __bool__(self) -> bool:
        return self.matches


def match_agent(
    *,
    expected_id: str | None,
    assigned_explicitly: bool,
    hostnames: set[str],
    reported_id: str | None,
    reported_hostname: str | None,
) -> AgentMatch:
    """Decide whether the agent that answered belongs to the expected machine."""
    expected = (expected_id or "").strip().casefold()
    reported = (reported_id or "").strip().casefold()
    if expected and reported == expected:
        return AgentMatch(True, "Agent-ID stimmt überein")
    if assigned_explicitly:
        # A person pinned this mapping, so a different ID is a real contradiction
        # and must not be waved through by a coincidental host name.
        return AgentMatch(False, "zugeordnete Agent-ID stimmt nicht")
    if hostnames & name_values(reported_hostname):
        return AgentMatch(True, "Hostname stimmt überein")
    return AgentMatch(False, "weder Agent-ID noch Hostname stimmen überein")


def mismatch_message(
    machine_name: str,
    expected_id: str | None,
    reported_id: str | None,
    reported_hostname: str | None,
    reason: str,
) -> str:
    """The one wording both callers use when the agent does not belong here."""
    return (
        f"Der antwortende Agent gehört nicht zu {machine_name} ({reason}).\n\n"
        f"Erwartet: {expected_id or '-'}\n"
        f"Geantwortet hat: {reported_id or '-'} ({reported_hostname or 'ohne Hostname'})\n\n"
        "Das ist eine Identitätsprüfung, keine Rechtefrage — mit anderen "
        "Zugangsdaten ändert sich daran nichts. Entweder zeigt die "
        "Verbindungsadresse dieser Maschine auf einen anderen Rechner, oder der "
        "Agent dort läuft unter einer anderen Maschinen-ID. Korrigieren über "
        "Details → „Agent zuordnen …“."
    )


__all__ = [
    "AgentMatch",
    "machine_hostnames",
    "match_agent",
    "mismatch_message",
    "name_values",
]
