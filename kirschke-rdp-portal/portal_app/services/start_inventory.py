"""Mitgeliefertes Startinventar für den ersten Start eines Portals.

Ein neu installiertes Portal ohne eigenen Stand übernimmt diese Maschinen,
damit nicht jeder Kollege dieselben Rechner von Hand anlegt. Danach gehört der
Stand dem Portal selbst; spätere Pakete ändern ihn nicht mehr. Ein
eingetragenes gemeinsames Inventar bleibt davon unberührt.

Übernommen wird nur, was eine Maschine beschreibt -- nie, wer sich dort
anmeldet. Die Felder stehen deshalb auf einer Positivliste: Ein neues Feld im
Inventar landet erst dann im Startinventar, wenn es hier ausdrücklich steht.
Dieselbe Liste gilt beim Erzeugen (``deployment/build_start_inventory.py``)
und beim Laden.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from portal_app.models.workstation import Workstation
from shared.schemas import WorkstationSchema

logger = logging.getLogger(__name__)

START_INVENTORY_FILE = Path(__file__).resolve().parents[1] / "data" / "start-inventar.json"

#: Was eine Maschine beschreibt. Anmeldenamen (``login_accounts``,
#: ``username_hint``, ``rdp_access_users``), Live-Daten von Agent und Sitzung,
#: Markierungen und die Serveridentitäts-Ausnahme fehlen bewusst.
START_INVENTORY_FIELDS: tuple[str, ...] = (
    "workstation_id",
    "agent_workstation_id",
    "display_name",
    "hostname",
    "fqdn",
    "ip_address",
    "subnet_mask",
    "default_gateway",
    "dns_server",
    "connection_target_mode",
    "site",
    "description",
    "enabled",
    "allowed_entra_group_ids",
    "entra_sso_enabled",
    "gateway_hostname",
    "use_all_monitors",
    "redirect_clipboard",
    "redirect_drives",
    "redirect_printers",
    "redirect_audio",
    "screen_mode",
    "resolution",
)


def start_inventory_entry(item: dict) -> dict:
    """Nur die Felder der Positivliste, und nur die mit einem Wert."""
    return {
        key: item[key]
        for key in START_INVENTORY_FIELDS
        if key in item and item[key] not in (None, "", [])
    }


def load_start_inventory(path: Path | None = None) -> list[Workstation]:
    """Die Maschinen des Startinventars; leer, wenn es fehlt oder nicht lesbar ist.

    Ein kaputtes Startinventar darf den ersten Start nicht verhindern -- dann
    beginnt das Portal eben leer, wie vorher.
    """
    source = path or START_INVENTORY_FILE
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        workstations = [
            Workstation.from_schema(WorkstationSchema.model_validate(start_inventory_entry(item)))
            for item in data.get("workstations", [])
        ]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Startinventar %s nicht nutzbar: %s", source, exc)
        return []
    logger.info("Startinventar mit %d Maschinen geladen", len(workstations))
    return workstations


__all__ = [
    "START_INVENTORY_FIELDS",
    "START_INVENTORY_FILE",
    "load_start_inventory",
    "start_inventory_entry",
]
