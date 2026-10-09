"""Das Startinventar aus einem eigenen Portal-Stand erzeugen.

    python deployment/build_start_inventory.py <pfad>\\portal-state.json

Schreibt ``portal_app/data/start-inventar.json``. Übernommen werden nur die
Felder aus ``START_INVENTORY_FIELDS`` -- keine Anmeldenamen, keine
Reservierungen, keine Live-Daten. Was entfällt, wird aufgelistet, damit vor dem
Bauen sichtbar ist, was das Paket enthält.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal_app.services.start_inventory import (  # noqa: E402 - nach sys.path
    START_INVENTORY_FILE,
    start_inventory_entry,
)
from shared.schemas import WorkstationSchema  # noqa: E402 - nach sys.path


def build(state_path: Path, target: Path = START_INVENTORY_FILE) -> list[str]:
    """Das Startinventar schreiben und die weggelassenen Felder zurückgeben."""
    data = json.loads(state_path.read_text(encoding="utf-8-sig"))
    entries: list[dict] = []
    dropped: set[str] = set()
    for item in data.get("workstations", []):
        entry = start_inventory_entry(item)
        WorkstationSchema.model_validate(entry)  # bricht bei ungültigen Werten ab
        dropped.update(key for key, value in item.items()
                       if key not in entry and value not in (None, "", [], False))
        entries.append(entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"version": 1, "workstations": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return sorted(dropped)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("state", type=Path, help="portal-state.json des eigenen Portals")
    args = parser.parse_args()
    dropped = build(args.state)
    count = len(json.loads(START_INVENTORY_FILE.read_text(encoding="utf-8"))["workstations"])
    print(f"Startinventar: {START_INVENTORY_FILE} ({count} Maschinen)")
    if dropped:
        print("Nicht übernommen: " + ", ".join(dropped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
