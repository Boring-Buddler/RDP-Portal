"""Discover workstation connection data without requiring an installed agent."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class MachineDiscovery:
    """Connection facts collected from DNS or the local Windows network stack."""

    hostname: str = ""
    fqdn: str | None = None
    ip_address: str | None = None
    subnet_mask: str | None = None
    default_gateway: str | None = None
    dns_server: str | None = None
    message: str = ""

    def as_prefill(self) -> dict[str, str]:
        """Return values understood by the machine profile form."""
        return {
            "display_name": self.hostname or self.fqdn or self.ip_address or "Neue Maschine",
            "hostname": self.hostname,
            "fqdn": self.fqdn or "",
            "ip_address": self.ip_address or "",
            "subnet_mask": self.subnet_mask or "",
            "default_gateway": self.default_gateway or "",
            "dns_server": self.dns_server or "",
        }


def discover_local_machine() -> MachineDiscovery:
    """Read the active local IPv4 configuration using Windows' CIM interface."""
    hostname = socket.gethostname().strip()
    fqdn = _normalise_fqdn(socket.getfqdn(hostname), hostname)
    details = _local_network_details()
    hostname = details.get("hostname") or hostname
    fqdn = _normalise_fqdn(details.get("fqdn") or fqdn, hostname)
    return MachineDiscovery(
        hostname=hostname,
        fqdn=fqdn,
        ip_address=details.get("ip_address"),
        subnet_mask=details.get("subnet_mask"),
        default_gateway=details.get("default_gateway"),
        dns_server=details.get("dns_server"),
        message="Lokaler Rechner wurde automatisch erkannt.",
    )


def discover_remote_machine(target: str) -> MachineDiscovery:
    """Resolve an entered IP address, hostname, or FQDN through DNS.

    Remote subnet, gateway and DNS server deliberately are not guessed: Windows
    exposes them only through an agent or authorised remote management.
    """
    target = target.strip()
    if not target:
        return MachineDiscovery(message="Bitte zuerst eine IP-Adresse, einen Hostnamen oder FQDN eingeben.")

    try:
        ipaddress.ip_address(target)
        return _discover_from_ip(target)
    except ValueError:
        return _discover_from_name(target)


def _discover_from_ip(ip_address: str) -> MachineDiscovery:
    try:
        resolved_name, aliases, _ = socket.gethostbyaddr(ip_address)
    except socket.herror:
        return MachineDiscovery(
            ip_address=ip_address,
            message="Keine Reverse-DNS-Aufl\u00f6sung vorhanden. IP-Adresse wurde \u00fcbernommen.",
        )
    fqdn = _normalise_fqdn(resolved_name, "")
    hostname = fqdn.split(".", 1)[0] if fqdn else (aliases[0] if aliases else "")
    return MachineDiscovery(
        hostname=hostname,
        fqdn=fqdn,
        ip_address=ip_address,
        message="Hostname und FQDN wurden per Reverse DNS ermittelt.",
    )


def _discover_from_name(target: str) -> MachineDiscovery:
    hostname = target.split(".", 1)[0]
    fqdn = _normalise_fqdn(socket.getfqdn(target), hostname)
    try:
        ip_address = socket.gethostbyname(target)
    except socket.gaierror:
        return MachineDiscovery(
            hostname=hostname,
            fqdn=fqdn if fqdn != hostname else None,
            message="Der Name wurde nicht per DNS aufgel\u00f6st. Bitte IP-Adresse pr\u00fcfen oder manuell eintragen.",
        )
    return MachineDiscovery(
        hostname=hostname,
        fqdn=fqdn if fqdn != hostname else None,
        ip_address=ip_address,
        message="Hostname, FQDN und IP-Adresse wurden per DNS ermittelt.",
    )


def _normalise_fqdn(value: str | None, hostname: str) -> str | None:
    candidate = (value or "").strip().rstrip(".")
    if not candidate or candidate.lower() == hostname.lower() or "." not in candidate:
        suffix = os.environ.get("USERDNSDOMAIN", "").strip().strip(".")
        return f"{hostname}.{suffix}" if hostname and suffix else None
    return candidate


def _local_network_details() -> dict[str, str]:
    """Return a best-effort primary adapter config; empty on non-Windows hosts."""
    command = (
        "$config = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=TRUE' | "
        "ForEach-Object { $ipv4 = @($_.IPAddress | Where-Object { $_ -match '^\\d{1,3}(\\.\\d{1,3}){3}$' })[0]; "
        "if ($ipv4) { [PSCustomObject]@{ Hostname=$env:COMPUTERNAME; Fqdn=\"$env:COMPUTERNAME.$env:USERDNSDOMAIN\"; "
        "IPAddress=$ipv4; SubnetMask=@($_.IPSubnet | Where-Object { $_ -match '^\\d{1,3}(\\.\\d{1,3}){3}$' })[0]; "
        "DefaultGateway=@($_.DefaultIPGateway | Where-Object { $_ -match '^\\d{1,3}(\\.\\d{1,3}){3}$' })[0]; "
        "DnsServer=@($_.DNSServerSearchOrder | Where-Object { $_ -match '^\\d{1,3}(\\.\\d{1,3}){3}$' })[0] } } } | "
        "Select-Object -First 1 | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 and result.stdout.strip() else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    return {
        "hostname": str(payload.get("Hostname") or "").strip(),
        "fqdn": str(payload.get("Fqdn") or "").strip(),
        "ip_address": str(payload.get("IPAddress") or "").strip(),
        "subnet_mask": str(payload.get("SubnetMask") or "").strip(),
        "default_gateway": str(payload.get("DefaultGateway") or "").strip(),
        "dns_server": str(payload.get("DnsServer") or "").strip(),
    }


__all__ = ["MachineDiscovery", "discover_local_machine", "discover_remote_machine"]
