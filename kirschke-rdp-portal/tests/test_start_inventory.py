"""Das mitgelieferte Startinventar: Maschinen ja, Anmeldenamen nie."""

from __future__ import annotations

import json
from pathlib import Path

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
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


def test_a_restore_overwrites_the_own_state_and_keeps_a_backup(tmp_path: Path):
    store = LocalStore(tmp_path / "portal-state.json")
    seed = load_start_inventory()
    own = Workstation(workstation_id="WS-099", display_name="Eigene", hostname="PC99")
    store.save([own], MockUser.create_user(), [])

    backup = store.reset_to_start_inventory(seed)

    machines, _, reservations = LocalStore(store.path).load([], MockUser.create_user())
    assert [ws.workstation_id for ws in machines] == [ws.workstation_id for ws in seed]
    assert reservations == []
    assert backup == tmp_path / "portal-state.vorher.json"
    kept = json.loads(backup.read_text(encoding="utf-8"))["workstations"]
    assert [item["workstation_id"] for item in kept] == ["WS-099"]


def test_a_restore_never_touches_a_shared_inventory(tmp_path: Path):
    import pytest

    store = LocalStore(tmp_path / "portal-state.json")
    store.agent_config_path.write_text(
        json.dumps({"inventory_directory": str(tmp_path / "freigabe")}), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        store.reset_to_start_inventory(load_start_inventory())
    assert not store.path.exists()


def test_new_start_machines_are_offered_once(tmp_path: Path):
    store = LocalStore(tmp_path / "portal-state.json")
    seed = load_start_inventory()
    first, rest = seed[:1], seed[1:]

    # Ein Portal aus der Zeit vor dem Abgleich: Es kennt nur eine Maschine.
    assert [ws.workstation_id for ws in store.new_start_machines(first, seed)] == [
        ws.workstation_id for ws in rest
    ]
    # Danach gelöschte Startmaschinen kommen nicht wieder.
    assert store.new_start_machines(first, seed) == []
    newer = Workstation(workstation_id="WS-006", display_name="Neu", hostname="PC06")
    assert [ws.workstation_id for ws in store.new_start_machines(first, [*seed, newer])] == [
        "WS-006"
    ]


def test_loading_never_brings_back_machines_from_the_fallback(tmp_path: Path):
    """``on_refresh`` übergibt die Liste im Speicher -- gelöschte Maschinen blieben sonst."""
    store = LocalStore(tmp_path / "portal-state.json")
    seed = load_start_inventory()
    store.save(seed[:2], MockUser.create_user(), [])

    machines, _, _ = store.load(seed, MockUser.create_user())

    assert [ws.workstation_id for ws in machines] == ["WS-001", "WS-002"]


def test_the_standard_status_share_follows_the_host_name():
    from portal_app.services.share_connection import agent_status_share

    assert agent_status_share("PC07.prof-kirschke.local") == r"\\PC07\RDP-Status"
    assert agent_status_share("192.168.2.66") == r"\\192.168.2.66\RDP-Status"
    assert agent_status_share("") == ""


def test_fallback_setup_works_like_the_dialog_once_per_server(monkeypatch):
    from portal_app.services import share_connection

    calls: list[tuple] = []
    monkeypatch.setattr(share_connection, "load_reader_credentials", lambda: ("PortalLeser", "geheim"))

    def connect(path, username, password, remember):
        calls.append((path, username, password, remember))
        if "PC07" in path:
            raise ValueError("Windows konnte die Freigabe nicht verbinden (Fehler 53). VPN prüfen.")
        return path, "Freigabe erreichbar; 1 JSON-Datei(en) lesbar."

    monkeypatch.setattr(share_connection, "connect_share", connect)
    fallback: list[str] = []
    monkeypatch.setattr(
        share_connection, "connect_status_share", lambda path: fallback.append(path) or (True, "")
    )

    results = share_connection.setup_status_fallbacks({
        "WS-1": r"\\NB12KI\RDP-Status",
        "WS-2": r"\\nb12ki\RDP-Status",
        "WS-3": r"\\PC07\RDP-Status",
    })

    assert results["WS-1"][0] and results["WS-2"][0]
    assert not results["WS-3"][0]
    assert calls == [
        (r"\\NB12KI\RDP-Status", "PortalLeser", "geheim", True),
        (r"\\PC07\RDP-Status", "PortalLeser", "geheim", True),
    ]
    # Ausgeschaltet heisst: kein zweiter SMB-Timeout.
    assert fallback == []


def test_fallback_setup_uses_an_existing_connection_under_another_account(monkeypatch):
    from portal_app.services import share_connection

    monkeypatch.setattr(share_connection, "load_reader_credentials", lambda: ("PortalLeser", "geheim"))

    def connect(*args, **kwargs):
        raise ValueError("Windows ist mit diesem Rechner bereits unter einem anderen Konto verbunden.")

    monkeypatch.setattr(share_connection, "connect_share", connect)
    monkeypatch.setattr(
        share_connection, "connect_status_share", lambda path: (True, "bestehende Verbindung")
    )

    assert share_connection.setup_status_fallbacks({"WS-1": r"\\PC07\RDP-Status"}) == {
        "WS-1": (True, "bestehende Verbindung")
    }
