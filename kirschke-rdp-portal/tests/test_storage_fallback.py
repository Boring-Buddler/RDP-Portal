"""Ein nicht erreichbarer Speicherort darf das Portal nicht töten.

Der Standardspeicherort liegt im synchronisierten SharePoint-Ordner. Auf einem
PC, auf dem dieser Ordner nie eingerichtet wurde, läuft ``mkdir(parents=True)``
bis ``C:/Users`` hoch und wird dort abgewiesen -- das beendete das Portal mit
einem ungefangenen Traceback, bevor überhaupt ein Fenster erschien.

Ausweichen auf einen lokalen Ordner hält das Portal benutzbar. Es hört damit
aber auf, seinen Stand zu teilen, und genau das muss gesagt werden.
"""

import json
from unittest.mock import Mock

import pytest

from portal_app.models.user import MockUser
from portal_app.services.local_store import LocalStore
from shared import agent_paths


def test_redirect_uses_each_readers_profile(tmp_path, monkeypatch):
    author = tmp_path / "profiles" / "author"
    reader = tmp_path / "profiles" / "reader"
    previous = tmp_path / "previous"
    previous.mkdir()
    monkeypatch.setenv("USERPROFILE", str(author))
    LocalStore._write_redirect_marker(previous, author / "library" / "remote")
    marker = json.loads((previous / "storage-location.json").read_text(encoding="utf-8"))
    assert "author" not in marker["storage_directory"]
    monkeypatch.setenv("USERPROFILE", str(reader))
    assert agent_paths.expand_directory(marker["storage_directory"]) == reader / "library" / "remote"


@pytest.mark.parametrize("source", ["config", "redirect"])
def test_old_foreign_profile_path_recovers_existing_inventory(tmp_path, monkeypatch, source):
    profile = tmp_path / "profiles" / "reader"
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("LOCALAPPDATA", str(profile / "AppData" / "Local"))
    target = profile / "library" / "remote"
    target.mkdir(parents=True)
    (target / "portal-state.json").write_text("{}", encoding="utf-8")
    path = (LocalStore._config_path() if source == "config" else
            agent_paths.legacy_portal_directory() / "storage-location.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"storage_directory": str(
        profile.parent / "author" / "library" / "remote"
    )}), encoding="utf-8")
    store = LocalStore()
    assert store.directory == tmp_path / "portal" / "state"
    assert store._legacy_configured_directory() == target


def test_missing_foreign_profile_path_does_not_create_a_fake_shared_folder(tmp_path, monkeypatch):
    profile = tmp_path / "profiles" / "reader"
    monkeypatch.setenv("USERPROFILE", str(profile))
    foreign = profile.parent / "author" / "library"
    assert agent_paths.resolve_portal_storage(foreign) == foreign
    assert not profile.exists()


def test_reachable_explicit_foreign_path_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "reader"))
    foreign = tmp_path / "author" / "library"
    foreign.mkdir(parents=True)
    assert agent_paths.resolve_portal_storage(foreign) == foreign


def test_unc_path_is_saved_without_profile_substitution(monkeypatch):
    monkeypatch.setenv("USERPROFILE", r"C:\Users\example")
    path = r"\\server\portal\remote"
    assert agent_paths.portable_directory(path) == path


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    return LocalStore(tmp_path / "geteilt" / "portal-state.json")


@pytest.fixture
def window(store, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    widget = MainWindow(automatic_live_status=False)
    qtbot.addWidget(widget)
    return widget


def refuse_once(store, monkeypatch):
    """Der erste Schreibversuch scheitert wie auf dem fremden PC, danach geht es."""
    real_save = store.save
    calls = []

    def save(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(5, "Zugriff verweigert")
        return real_save(*args, **kwargs)

    monkeypatch.setattr(store, "save", save)


# --- Ausweichen ---------------------------------------------------------------

def test_the_store_moves_into_the_local_folder(store, tmp_path):
    local = store.use_local_fallback()

    assert tmp_path / "lokal" in local.parents or local.is_relative_to(tmp_path / "lokal")
    assert store.path.parent == local
    assert store.events_path.parent == local


def test_switching_resets_the_change_detection(store):
    """Sonst meldete der nächste Schreibvorgang einen Konflikt mit einer Datei,
    die das Portal gar nicht mehr benutzt."""
    store.save([], MockUser.create_user(), [])
    assert store._state_signature is not None

    store.use_local_fallback()

    assert store._state_signature is None


# --- Verhalten beim Start -----------------------------------------------------

def test_a_reachable_location_is_left_alone(window, store, tmp_path):
    assert window._storage_fallback_notice == ""
    assert store.path == tmp_path / "geteilt" / "portal-state.json"


def test_a_refused_location_does_not_end_the_portal(window, store, monkeypatch, tmp_path):
    refuse_once(store, monkeypatch)
    window.store.path.unlink(missing_ok=True)

    window._save_initial_state()

    assert window._storage_fallback_notice
    assert store.path.is_relative_to(tmp_path / "lokal")
    assert store.path.exists()


def test_the_notice_names_both_locations(window, store, monkeypatch, tmp_path):
    intended = str(store.directory)
    refuse_once(store, monkeypatch)

    window._save_initial_state()

    notice = window._storage_fallback_notice
    assert intended in notice
    assert str(tmp_path / "lokal") in notice
    # Der Preis muss dastehen, nicht nur der Ausweichpfad.
    assert "NICHT" in notice


def test_a_completely_unwritable_system_still_starts(window, store, monkeypatch):
    monkeypatch.setattr(
        store, "save", Mock(side_effect=PermissionError(5, "Zugriff verweigert"))
    )
    monkeypatch.setattr(
        store, "use_local_fallback", Mock(side_effect=PermissionError(5, "Zugriff verweigert"))
    )

    with pytest.raises(PermissionError):
        store.use_local_fallback()

    monkeypatch.setattr(store, "use_local_fallback", Mock(return_value=store.directory))
    window._save_initial_state()

    assert "merkt sich aber nichts" in window._storage_fallback_notice


def test_the_notice_is_shown_only_once(window, monkeypatch):
    window._storage_fallback_notice = "Speicherort nicht erreichbar"
    warning = Mock()
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.warning", warning)

    window._show_storage_fallback_notice()
    window._show_storage_fallback_notice()

    assert warning.call_count == 1


# --- Welcher Ordner überhaupt gewählt wird -------------------------------------

def test_the_default_is_relative_to_the_program(tmp_path, monkeypatch):
    """Kein Raten mehr, wie jemandes OneDrive aufgebaut ist."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))

    assert LocalStore().directory == tmp_path / "portal" / "state"


def test_an_existing_installation_remembers_its_old_folder_for_import(tmp_path, monkeypatch):
    """Wer seinen Stand dort schon fuehrt, muss ihn dort weiter finden."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    legacy = agent_paths.legacy_portal_directory()
    legacy.mkdir(parents=True)
    (legacy / "portal-state.json").write_text("{}", encoding="utf-8")

    store = LocalStore()
    assert store.directory == tmp_path / "portal" / "state"
    assert store._legacy_configured_directory() == legacy


def test_an_empty_old_folder_proves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    agent_paths.legacy_portal_directory().mkdir(parents=True)

    assert LocalStore().directory == tmp_path / "portal" / "state"


def test_the_old_folder_is_never_created(tmp_path, monkeypatch):
    """Ein Abbild, das nie synchronisiert, ist schlimmer als gar keiner."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    store = LocalStore()

    store.save([], MockUser.create_user(), [])

    assert not agent_paths.legacy_portal_directory().exists()


def test_an_explicit_setting_beats_both(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "profil"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))
    gewuenscht = tmp_path / "irgendwo" / "gemeinsam"

    store = LocalStore(gewuenscht / "portal-state.json")

    assert store.directory == gewuenscht


def test_the_local_directory_is_never_a_network_path(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "lokal"))

    assert not str(LocalStore.local_directory()).startswith(chr(92) * 2)


def test_a_broken_event_log_does_not_end_the_portal(store, monkeypatch, qtbot):
    """Der zweite Weg, auf dem ein unerreichbarer Ordner das Portal beendet hat."""
    from unittest.mock import Mock

    from portal_app.ui.main_window import MainWindow

    monkeypatch.setattr(
        store, "initialize_event_log", Mock(side_effect=PermissionError(5, "Zugriff verweigert"))
    )
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)

    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)

    assert window is not None
