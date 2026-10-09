"""Das mitgelieferte Startinventar: Maschinen ja, Anmeldenamen nie."""

from __future__ import annotations

import json
from pathlib import Path

from portal_app.models.user import MockUser
from portal_app.services.local_store import LocalStore
from portal_app.services.start_inventory import (
    START_INVENTORY_FIELDS,
    START_INVENTORY_FILE,
    load_start_inventory,
)

PERSONAL_FIELDS = ("login_accounts", "username_hint", "rdp_access_users", "current_session_user")


def test_the_shipped_inventory_holds_the_known_machines():
    machines = {ws.workstation_id: ws for ws in load_start_inventory()}

    assert sorted(machines) == ["WS-001", "WS-002", "WS-003", "WS-004", "WS-005"]
    remote = machines["WS-002"]
    assert (remote.hostname, remote.ip_address, remote.site) == (
        "Remote-Ettlingen", "192.168.2.66", "Ettlingen",
    )
    assert machines["WS-003"].site == "München"


def test_the_shipped_file_names_no_account():
    data = json.loads(START_INVENTORY_FILE.read_text(encoding="utf-8"))

    for item in data["workstations"]:
        assert set(item) <= set(START_INVENTORY_FIELDS)
    for ws in load_start_inventory():
        assert ws.login_accounts == []
        assert not ws.username_hint
        assert ws.rdp_access_users == []
        assert ws.trust_unverified_server is False


def test_fields_outside_the_list_are_ignored_when_loading(tmp_path: Path):
    source = tmp_path / "start.json"
    source.write_text(json.dumps({"workstations": [{
        "workstation_id": "WS-9", "display_name": "PC09", "hostname": "PC09",
        "login_accounts": ["AzureAD\\becker@prof-kirschke.de"],
        "username_hint": "becker@prof-kirschke.de",
        "rdp_access_users": ["AzureAD\\becker@prof-kirschke.de"],
        "current_session_user": "AzureAD\\ChristianBecker",
        "trust_unverified_server": True,
    }]}), encoding="utf-8")

    [ws] = load_start_inventory(source)

    assert ws.hostname == "PC09"
    assert ws.login_accounts == [] and not ws.username_hint and ws.rdp_access_users == []
    assert not ws.current_session_user
    assert ws.trust_unverified_server is False


def test_a_missing_or_broken_file_means_an_empty_start(tmp_path: Path):
    assert load_start_inventory(tmp_path / "fehlt.json") == []
    broken = tmp_path / "kaputt.json"
    broken.write_text("{nicht json", encoding="utf-8")
    assert load_start_inventory(broken) == []


def test_the_start_inventory_only_fills_an_empty_store(tmp_path: Path):
    store = LocalStore(tmp_path / "portal-state.json")
    seed = load_start_inventory()

    machines, _, _ = store.load(seed, MockUser.create_user())
    assert [ws.workstation_id for ws in machines] == [ws.workstation_id for ws in seed]

    store.save(machines[:1], MockUser.create_user(), [])
    again, _, _ = LocalStore(tmp_path / "portal-state.json").load(seed, MockUser.create_user())
    assert [ws.workstation_id for ws in again] == ["WS-001"]


def test_the_build_script_drops_personal_fields(tmp_path: Path):
    from deployment.build_start_inventory import build

    state = tmp_path / "portal-state.json"
    state.write_text(json.dumps({"workstations": [{
        "workstation_id": "WS-9", "display_name": "PC09", "hostname": "PC09",
        "ip_address": "192.168.2.9", "site": "Ettlingen",
        "login_accounts": ["AzureAD\\becker@prof-kirschke.de"],
        "selected_login_account": "AzureAD\\becker@prof-kirschke.de",
        "username_hint": "becker@prof-kirschke.de",
        "agent_status": "online",
    }], "reservations": [{"id": "R1"}]}), encoding="utf-8")
    target = tmp_path / "start-inventar.json"

    dropped = build(state, target)

    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["workstations"] == [{
        "workstation_id": "WS-9", "display_name": "PC09", "hostname": "PC09",
        "ip_address": "192.168.2.9", "site": "Ettlingen",
    }]
    assert "reservations" not in written
    for field in ("login_accounts", "selected_login_account", "username_hint", "agent_status"):
        assert field in dropped
    for field in PERSONAL_FIELDS:
        assert field not in json.dumps(written)
