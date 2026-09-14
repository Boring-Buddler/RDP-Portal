"""Regression guard for finding B1: the configured interval drives the backoff.

The old code exposed ``_current_interval`` as a property whose getter read
``getattr(self, "__current_interval", 5)``.  A string is not name-mangled, so the
getter never saw the value the setter stored and always returned 5 --
``set_interval()`` was a no-op for the retry delay.
"""

import pytest

from portal_app.services import live_status_polling
from portal_app.services.live_status_polling import AutomaticLiveStatusPoller

TARGET = "ws01.example.test"


@pytest.fixture
def poller(qapp):
    created = AutomaticLiveStatusPoller()
    yield created
    created.stop()


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pin time.monotonic so retry deadlines can be asserted exactly."""
    monkeypatch.setattr(live_status_polling.time, "monotonic", lambda: 1_000.0)
    return 1_000.0


def _delay_after_consecutive_failures(poller, now: float, count: int) -> float:
    for _ in range(count):
        poller._on_failed("WS-001", TARGET, "Live-Abfrage fehlgeschlagen (53).")
    return poller._retry_after[TARGET] - now


def test_default_interval_is_five_seconds(poller) -> None:
    assert poller.interval_seconds == 5


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(2, 2), (5, 5), (30, 30), (60, 60), (1, 2), (0, 2), (900, 60), (-5, 2)],
)
def test_set_interval_stores_the_clamped_value(poller, configured: int, expected: int) -> None:
    poller.set_interval(configured)
    assert poller.interval_seconds == expected


def test_sixty_second_interval_backs_off_in_sixty_second_steps(poller, frozen_clock) -> None:
    """Before the fix every one of these was 5/10/20/40 regardless of the setting."""
    poller.set_interval(60)
    # 60 * 2**0 == 60, and the 60 s ceiling holds it there for later failures.
    assert _delay_after_consecutive_failures(poller, frozen_clock, 1) == 60


def test_five_second_interval_doubles_then_stops_at_the_ceiling(poller, frozen_clock) -> None:
    poller.set_interval(5)
    # 5 * 2**0, 2**1, 2**2, 2**3, then the exponent is capped at 3.
    assert [
        _delay_after_consecutive_failures(poller, frozen_clock, 1) for _ in range(5)
    ] == [5, 10, 20, 40, 40]


def test_thirty_second_interval_reaches_the_ceiling_on_the_second_failure(
    poller, frozen_clock
) -> None:
    poller.set_interval(30)
    assert [
        _delay_after_consecutive_failures(poller, frozen_clock, 1) for _ in range(3)
    ] == [30, 60, 60]


def test_a_longer_interval_waits_longer_than_a_short_one(poller, frozen_clock) -> None:
    """The property bug made these two identical; they must now differ."""
    poller.set_interval(2)
    short = _delay_after_consecutive_failures(poller, frozen_clock, 1)
    poller._failure_counts.clear()
    poller._retry_after.clear()
    poller.set_interval(45)
    long = _delay_after_consecutive_failures(poller, frozen_clock, 1)
    assert short == 2
    assert long == 45
    assert long > short


def test_success_clears_the_backoff(poller) -> None:
    poller.set_interval(10)
    poller._on_failed("WS-003", TARGET, "fehlgeschlagen")
    assert TARGET in poller._retry_after
    poller._on_succeeded("WS-003", TARGET, object(), 12)
    assert TARGET not in poller._retry_after
    assert TARGET not in poller._failure_counts


def test_request_many_applies_the_interval_it_is_given(poller, frozen_clock) -> None:
    poller.request_many([], 25)
    assert poller.interval_seconds == 25


def test_no_unmangled_private_attribute_survives(poller) -> None:
    poller.set_interval(42)
    assert "_AutomaticLiveStatusPoller__current_interval" not in vars(poller)
    assert not hasattr(poller, "_current_interval")
    assert poller.interval_seconds == 42
