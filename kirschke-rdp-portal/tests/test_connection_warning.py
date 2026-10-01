"""Aus dem toten "Maschine besetzt" wird ein Verbinden-Knopf mit Warnung.

Vorher war der Knopf bei einer belegten oder fremd gebuchten Maschine
ausgegraut. Zusammen mit der Reservierungssperre ergab das einen Zustand, aus
dem niemand mehr herauskam: Wer gebucht hatte, kam wegen der laufenden fremden
Sitzung nicht auf die Maschine; wer angemeldet war, kam wegen der Buchung weder
zurück auf seine eigene Sitzung noch konnte er sie beenden.

Die Karte sieht unverändert aus -- Farbe und Randstärke sagen weiterhin "hier
sitzt jemand anderes". Was sich ändert: Der Klick führt zu einer Warnung statt
ins Leere.
"""

from datetime import datetime, timedelta

import pytest

from portal_app.models.reservation import Reservation
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.reservation_access import apply_reservations
from portal_app.ui.machine_actions import (
    SINGLE_SESSION_CONSEQUENCE,
    MachineState,
    connection_warning,
    describe_actions,
    occupant_names,
)
from shared.enums import AgentStatus, SessionState

OTHER = "WORKSTATION\\kollege"


def user() -> MockUser:
    person = MockUser.create_user()
    person.upn = "becker@x.de"
    person.windows_identity = "NB12KI\\Becker"
    person.rdp_username = None
    person.rdp_domain = None
    return person


def machine(state: SessionState = SessionState.NONE, **kwargs) -> Workstation:
    workstation = Workstation(
        "WS-1", "Rechenknecht", "RECHENKNECHT",
        agent_status=AgentStatus.ONLINE,
        current_session_state=state,
        **kwargs,
    )
    workstation.agent_status_source = "live"
    return workstation


def occupied(state: SessionState = SessionState.CONNECTED) -> Workstation:
    return machine(
        state,
        current_session_user=OTHER,
        agent_sessions=[{
            "session_id": 4,
            "full_username": OTHER,
            "session_state": state.value,
            "login_time": "2026-09-16T08:00:00+00:00",
        }],
    )


# --- Wann gewarnt wird -------------------------------------------------------


def test_a_free_machine_needs_no_warning():
    assert connection_warning(machine(), user()) is None


def test_a_foreign_session_warns_and_names_the_consequence():
    warning = connection_warning(occupied(), user())

    assert "kollege" in warning
    assert "Rechenknecht" in warning
    assert SINGLE_SESSION_CONSEQUENCE in warning


def test_a_disconnected_foreign_session_says_nobody_is_looking():
    """Der Fall, in dem Nachfragen am ehesten etwas bringt."""
    warning = connection_warning(occupied(SessionState.DISCONNECTED), user())

    assert "nicht verbunden" in warning
    assert SINGLE_SESSION_CONSEQUENCE in warning


def test_a_foreign_booking_without_a_session_threatens_nothing():
    """Gebucht, aber niemand angemeldet: Es geht nichts verloren, also keine Drohung."""
    workstation = machine()
    workstation.reservation_block_reason = "Reserviert für kollege@x.de bis 17:00"

    warning = connection_warning(workstation, user())

    assert "Reserviert für kollege@x.de" in warning
    assert SINGLE_SESSION_CONSEQUENCE not in warning
    assert "sprich dich mit der buchenden Person ab" in warning


def test_your_own_booking_is_not_a_warning():
    now = datetime.now()
    workstation = machine()
    booking = Reservation("WS-1", "Arbeit", now, now + timedelta(hours=1), "becker@x.de")

    apply_reservations([workstation], [booking], "becker@x.de", now)

    assert connection_warning(workstation, user()) is None


def test_a_caller_may_pass_a_freshly_read_booking():
    """Zwischen dem letzten Abgleich und dem Klick kann jemand gebucht haben."""
    workstation = machine()

    warning = connection_warning(
        workstation, user(), reservation_block_reason="Gerade eben gebucht"
    )

    assert "Gerade eben gebucht" in warning


# --- Der Knopf ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("workstation_factory", "state"),
    [
        (lambda: occupied(), MachineState.OCCUPIED_OTHER),
        (lambda: occupied(SessionState.DISCONNECTED), MachineState.OCCUPIED_OTHER_IDLE),
    ],
)
def test_an_occupied_machine_offers_a_connect_button(workstation_factory, state):
    actions = describe_actions(workstation_factory(), user())

    assert actions.state is state
    assert actions.primary_text == "Trotzdem verbinden"
    assert actions.primary_enabled


def test_the_card_keeps_its_reticent_look():
    """Klickbar heißt nicht "sieht aus wie frei" -- das Design bleibt."""
    taken = describe_actions(occupied(), user())
    free = describe_actions(machine(), user())

    assert taken.color != free.color
    assert taken.color.alphaF() < free.color.alphaF()


def test_a_maintenance_flag_stays_a_hard_stop():
    """Was jemand bewusst gesperrt hat, überstimmt man nicht per Warnung."""
    from shared.enums import ManualFlagType

    actions = describe_actions(machine(manual_flag_type=ManualFlagType.MAINTENANCE), user())

    assert actions.state is MachineState.BLOCKED
    assert not actions.primary_enabled


# --- Wer genannt wird --------------------------------------------------------


def test_without_a_report_the_windows_account_is_what_is_known():
    assert occupant_names(occupied(), user()) == [OTHER]


def test_a_reported_person_is_named_instead_of_the_account():
    workstation = occupied()
    workstation.agent_session_claims = [{
        "account": OTHER,
        "owner_upn": "kollege@x.de",
        "owner_display": "Kollege Meier",
        "session_id": 4,
        "login_time": "2026-09-16T08:00:00+00:00",
    }]

    assert occupant_names(workstation, user()) == ["Kollege Meier"]
    assert "Kollege Meier" in connection_warning(workstation, user())
