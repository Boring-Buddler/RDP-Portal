"""Guard for finding S2: the local admin gate now rate-limits guessing.

.env.example documented MAX_FAILED_LOGIN_ATTEMPTS and LOCKOUT_DURATION_MINUTES;
neither was implemented, so attempts were unbounded.
"""

import pytest

from portal_app.services import admin_security
from portal_app.services.admin_security import (
    LOCKOUT_SECONDS,
    MAX_FAILED_ATTEMPTS,
    AdminLockoutError,
    LocalAdminPasswordStore,
)

PASSWORD = "Korrektes-Kennwort-2026"


@pytest.fixture
def store(tmp_path):
    created = LocalAdminPasswordStore(tmp_path / "admin-security.json")
    created.set_password(PASSWORD)
    return created


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


def test_a_damaged_file_also_counts_as_a_failed_attempt(tmp_path) -> None:
    path = tmp_path / "admin-security.json"
    path.write_text("{not json", encoding="utf-8")
    store = LocalAdminPasswordStore(path)
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert store.verify_password("irgendetwas") is False
    assert store.lockout_remaining_seconds() == LOCKOUT_SECONDS


def test_setting_a_new_password_clears_a_lockout(store, clock) -> None:
    for _ in range(MAX_FAILED_ATTEMPTS):
        store.verify_password("falsch")
    assert store.lockout_remaining_seconds() == LOCKOUT_SECONDS
    store.set_password("Neues-Kennwort-2026")
    assert store.lockout_remaining_seconds() == 0
    assert store.verify_password("Neues-Kennwort-2026") is True


def test_counter_is_not_persisted_to_the_users_own_file(store, tmp_path) -> None:
    """A counter in that file would be as deletable as the hash beside it."""
    import json

    for _ in range(MAX_FAILED_ATTEMPTS):
        store.verify_password("falsch")
    data = json.loads((tmp_path / "admin-security.json").read_text(encoding="utf-8"))
    assert set(data) == {"version", "algorithm", "iterations", "salt", "password_hash"}
