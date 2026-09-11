"""Read-only pilot readiness report: python -m portal_app.preflight."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from portal_app.models.user import MockUser
from portal_app.rdp.generator import RDPFileGenerator
from portal_app.rdp.launcher import RDPSessionLauncher
from portal_app.services.local_store import LocalStore
from shared.agent_snapshot import load_agent_snapshots


def inspect_pilot(storage: Path | None = None) -> list[dict[str, str]]:
    checks = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    add("Windows", "ok" if sys.platform == "win32" else "error", sys.platform)
    launcher = RDPSessionLauncher()
    add("RDP-Client", "ok" if launcher._find_mstsc() else "error", "mstsc.exe im System gesucht")
    store = LocalStore(storage / "portal-state.json" if storage else None)
    if not store.path.exists():
        add("Inventar", "error", "Noch keine portal-state.json; zuerst Testmaschine registrieren.")
        return checks
    try:
        machines, _, reservations = store.load([], MockUser.create_user(), migrate=False)
    except (OSError, ValueError) as exc:
        add("Speicher", "error", str(exc))
        return checks
    add("Inventar", "ok" if machines else "error", f"{len(machines)} Maschinen, {len(reservations)} Reservierungen")
    generator = RDPFileGenerator()
    for machine in machines:
        try:
            generator._validate_profile(machine.get_rdp_profile())
            add(f"RDP-Profil {machine.workstation_id}", "ok", "Ziel und Optionen gültig")
        except Exception as exc:
            add(f"RDP-Profil {machine.workstation_id}", "error", str(exc))
    directory = store.agent_status_directory
    try:
        snapshots = load_agent_snapshots(directory)
        recent = sum(snapshot.age_seconds() <= 90 for snapshot in snapshots)
        add("Agent", "ok" if recent else "warning", f"{recent} aktuelle von {len(snapshots)} gültigen Statusdateien")
    except OSError as exc:
        add("Agent", "warning", str(exc))
    add("Betriebsabnahme", "warning", "RDP-Anmeldung, Schreibrechte, SMB/OneDrive-Synchronisierung und Agent-Autostart auf den Test-PCs prüfen.")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage", type=Path, help="Portal-Speicherverzeichnis")
    parser.add_argument("--json", action="store_true", help="Maschinenlesbarer Bericht")
    args = parser.parse_args()
    checks = inspect_pilot(args.storage)
    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            print(f"{check['status'].upper():7} {check['check']}: {check['detail']}")
    return 1 if any(check["status"] == "error" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
