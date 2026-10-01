"""Das Ereignisprotokoll kann in einem gemeinsamen Ordner liegen.

Der Anlass: Wer das Portal über das Setup installiert, bekommt es nach
``%LOCALAPPDATA%\\Programs\\KirschkeRDPPortal`` — und weil der gemeinsame Stand
neben der EXE liegt, ist er dort privat. Maschinen pro Person sind in Ordnung,
das Protokoll soll aber zeigen, wer wann welche Maschine benutzt hat, quer über
alle Beteiligten.

Ein eingetragener Ordner verschiebt nur das Protokoll. Alles andere bleibt, wo
es ist.
"""

import json

import pytest

from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore
from shared.agent_paths import is_private_program_location
from shared.enums import EventResult, EventSource, EventType


def event(identifier: str = "EVT-1", actor: str = "becker@x.de") -> SessionEvent:
    from datetime import datetime

    return SessionEvent(
        event_id=identifier,
        timestamp_utc=datetime.now(),
        event_type=EventType.LAUNCH_REQUESTED,
        workstation_id="WS-1",
        workstation_hostname="PC01",
        session_user_upn=actor,
        actor_entra_object_id="oid",
        actor_upn=actor,
        result=EventResult.SUCCESS,
        reason=None,
        source=EventSource.PORTAL,
    )


@pytest.fixture
def store(tmp_path):
    store = LocalStore(tmp_path / "eigen" / "portal-state.json")
    store.save([Workstation("WS-1", "Eins", "PC01")], MockUser.create_user(), [])
    return store


# --- Ohne Eintrag ------------------------------------------------------------


def test_without_a_folder_the_log_stays_beside_the_state(store):
    assert store.event_log_directory is None
    assert store.events_path.parent == store.path.parent


# --- Mit Eintrag -------------------------------------------------------------


def test_a_configured_folder_moves_only_the_log(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()

    store.set_event_log_directory(shared)

    assert store.events_path.parent == shared
    # Maschinen und Kontocache bleiben, wo sie sind.
    assert store.path.parent != shared
    assert store.directory_users_path.parent != shared


def test_events_are_written_to_the_shared_folder(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)

    store.append_event(event())

    assert (shared / "portal-events.jsonl").exists()
    assert not (store.path.parent / "portal-events.jsonl").exists()


def test_two_portals_see_each_others_events(tmp_path):
    """Der eigentliche Zweck: eine Datei, in die alle schreiben."""
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    user = MockUser.create_user()
    portals = []
    for name in ("becker", "kollege"):
        portal = LocalStore(tmp_path / name / "portal-state.json")
        portal.save([Workstation("WS-1", "Eins", "PC01")], user, [])
        portal.set_event_log_directory(shared)
        portals.append(portal)

    portals[0].append_event(event("EVT-A", "becker@x.de"))
    portals[1].append_event(event("EVT-B", "kollege@x.de"))

    for portal in portals:
        assert {item.event_id for item in portal.load_events()} == {"EVT-A", "EVT-B"}


def test_removing_the_folder_returns_the_log_to_the_own_state(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)

    assert store.set_event_log_directory(None) is None
    assert store.events_path.parent == store.path.parent


def test_the_setting_survives_a_restart(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)

    reopened = LocalStore(store.path)

    assert reopened.event_log_directory == shared


@pytest.mark.parametrize("bad", ["relativ/pfad", r"%GIBTESNICHT%\Protokoll"])
def test_an_unusable_path_is_refused(store, bad):
    """Relativ oder mit einem Platzhalter, den Windows nicht auflöst.

    Ein stehengebliebenes ``%…%`` zeigt nirgendwohin; ein relativer Pfad zeigt
    bei jedem woandershin, je nachdem, von wo das Portal gestartet wurde.
    """
    with pytest.raises(ValueError):
        store.set_event_log_directory(bad)


def test_the_setup_dialog_only_accepts_network_paths():
    """Ein lokaler Ordner teilt mit niemandem -- der Weg über die Oberfläche
    führt deshalb durch dieselbe Prüfung wie eine Agentenfreigabe."""
    from portal_app.services.share_connection import parse_share_path

    with pytest.raises(ValueError):
        parse_share_path(r"C:\Protokoll")


# --- Änderungserkennung ------------------------------------------------------


def test_a_colleagues_event_does_not_trigger_a_full_reload(store, tmp_path):
    """Sonst baute jeder fremde Eintrag alle fünf Sekunden das Inventar neu auf.

    In einem gemeinsamen Protokoll schreibt ständig jemand. Das an den
    Maschinenabgleich zu hängen hieße, bei jedem Eintrag den ganzen Stand neu zu
    lesen und das komplette Protokoll erneut zu prüfen.
    """
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)
    store.load([], MockUser.create_user())
    store.load_events()

    (shared / "portal-events.jsonl").write_text(
        json.dumps(event("EVT-FREMD").to_schema().model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )

    assert not store.has_external_changes()
    assert store.has_new_events()


def test_reading_the_events_acknowledges_them(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)
    store.append_event(event())
    store.load_events()

    assert not store.has_new_events()


def test_changed_machines_still_trigger_a_full_reload(store, tmp_path):
    shared = tmp_path / "gemeinsam"
    shared.mkdir()
    store.set_event_log_directory(shared)
    store.load([], MockUser.create_user())
    other = LocalStore(store.path)
    other.load([], MockUser.create_user())

    other.save(
        [Workstation("WS-1", "Umbenannt", "PC01")], MockUser.create_user(), []
    )

    assert store.has_external_changes()


# --- Die Erkennung der lokalen Installation ----------------------------------


def test_a_setup_installation_is_recognised_as_private(monkeypatch, tmp_path):
    r"""Der Fehler: Geprüft wurde gegen %LOCALAPPDATA%\KirschkeRDPPortal.

    Das Setup installiert nach %LOCALAPPDATA%\Programs\KirschkeRDPPortal — ein
    anderer Pfad, die Prüfung traf ihn nie, und die Anzeige versprach dort eine
    SharePoint-Verteilung, die es nicht gibt.
    """
    local = tmp_path / "AppData" / "Local"
    (local / "Programs" / "KirschkeRDPPortal" / "state").mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))

    assert is_private_program_location(local / "Programs" / "KirschkeRDPPortal" / "state")


def test_a_synced_folder_is_not_private(monkeypatch, tmp_path):
    """Ein synchronisierter Ordner liegt nie unter %LOCALAPPDATA%."""
    local = tmp_path / "AppData" / "Local"
    local.mkdir(parents=True)
    synced = tmp_path / "Firma" / "Dokumente" / "Portal" / "state"
    synced.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    assert not is_private_program_location(synced)
