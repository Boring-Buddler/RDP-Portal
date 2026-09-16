"""Guard for finding S2: the global admin gate now rate-limits guessing.

.env.example documented MAX_FAILED_LOGIN_ATTEMPTS and LOCKOUT_DURATION_MINUTES;
neither was implemented, so attempts were unbounded.
"""

import pytest

from portal_app.services import admin_security
from portal_app.services.admin_security import (
    LOCKOUT_SECONDS,
    MAX_FAILED_ATTEMPTS,
    AdminLockoutError,
    GlobalAdminPasswordVerifier,
)

PASSWORD = "KirschkeKirschke"


@pytest.fixture
def store():
    return GlobalAdminPasswordVerifier()


@pytest.fixture
def clock(monkeypatch):
    current = {"now": 1_000.0}
    monkeypatch.setattr(admin_security.time, "monotonic", lambda: current["now"])
    return current


def test_correct_password_verifies(store) -> None:
    assert store.verify_password(PASSWORD) is True


def test_failures_below_the_limit_do_not_lock(store) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert store.verify_password("falsch") is False
    assert store.lockout_remaining_seconds() == 0
    assert store.verify_password(PASSWORD) is True


def test_the_limit_triggers_a_lockout(store, clock) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert store.verify_password("falsch") is False
    assert store.lockout_remaining_seconds() == LOCKOUT_SECONDS
    # Even the correct password is refused while the gate is paused.
    with pytest.raises(AdminLockoutError):
        store.verify_password(PASSWORD)


def test_lockout_expires_and_then_accepts_the_password(store, clock) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        store.verify_password("falsch")
    clock["now"] += LOCKOUT_SECONDS - 1
    with pytest.raises(AdminLockoutError):
        store.verify_password(PASSWORD)
    clock["now"] += 2
    assert store.lockout_remaining_seconds() == 0
    assert store.verify_password(PASSWORD) is True


def test_a_success_resets_the_failure_counter(store) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        store.verify_password("falsch")
    assert store.verify_password(PASSWORD) is True
    # The counter restarted, so the next near-miss run must not lock either.
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        assert store.verify_password("falsch") is False
    assert store.lockout_remaining_seconds() == 0


def test_lockout_message_names_the_remaining_minutes(store, clock) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        store.verify_password("falsch")
    with pytest.raises(AdminLockoutError) as caught:
        store.verify_password(PASSWORD)
    assert "15 Minute" in str(caught.value)
    assert caught.value.remaining_seconds == LOCKOUT_SECONDS


@pytest.mark.parametrize("old_config", [None, "{not json", '{"password_hash":"old-local-hash"}'])
def test_global_password_works_with_new_and_existing_profiles(tmp_path, monkeypatch, old_config):
    for name in ("first", "second"):
        local_data = tmp_path / name
        monkeypatch.setenv("LOCALAPPDATA", str(local_data))
        path = local_data / "KirschkeRDPPortal" / "admin-security.json"
        if old_config is not None:
            path.parent.mkdir(parents=True)
            path.write_text(old_config, encoding="utf-8")
        verifier = GlobalAdminPasswordVerifier()
        assert verifier.verify_password(PASSWORD)
        assert not verifier.verify_password("Altes-lokales-Passwort")
        if old_config is None:
            assert not path.exists()
        else:
            assert path.read_text(encoding="utf-8") == old_config


def test_password_is_case_sensitive_and_exact(store):
    for password in (PASSWORD.lower(), PASSWORD + " ", " " + PASSWORD, "Kirschke", ""):
        assert not store.verify_password(password)


def test_unlock_requires_global_password_and_locking_requires_it_again(tmp_path, monkeypatch, qtbot):
    from unittest.mock import Mock

    from portal_app.services.local_store import LocalStore
    from portal_app.ui.main_window import MainWindow

    monkeypatch.setenv("RDP_PORTAL_DIRECTORY_MODE", "local")
    local_store = LocalStore(tmp_path / "portal-state.json")
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: local_store)
    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    prompt = Mock(return_value=("wrong-local-password", True))
    monkeypatch.setattr("portal_app.ui.main_window.QInputDialog.getText", prompt)
    monkeypatch.setattr("portal_app.ui.main_window.QMessageBox.warning", Mock())
    assert not window._request_admin_access()
    assert not window._admin_unlocked
    prompt.return_value = (PASSWORD, True)
    assert window._request_admin_access()
    assert window._admin_unlocked
    assert "Globales" in window.admin_view.access_status.text()
    window._lock_admin()
    assert not window._admin_unlocked
    prompt.return_value = ("", False)
    assert not window._request_admin_access()
    assert not window._admin_unlocked
