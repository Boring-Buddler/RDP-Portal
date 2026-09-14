"""Regression guard for finding B3 in the agent's session state classification.

Two defects were fixed here:
  * an unmapped transition fell through to EventType.LAUNCH_REQUESTED, putting a
    portal-initiated event type into the agent's audit trail;
  * the reason string read ``connect_state.name`` although the field is
    ``WTS_CONNECTSTATE_CLASS | None`` and defaults to None.
"""

import pytest

from shared.enums import EventType
from workstation_agent.eventlog.handler import EventLogConfig, EventQueue, SessionEventDetector
from workstation_agent.wts.monitor import WTS_CONNECTSTATE_CLASS, WTSSessionInfo

ACTIVE = WTS_CONNECTSTATE_CLASS.WTSActive
CONNECTED = WTS_CONNECTSTATE_CLASS.WTSConnected
CONNECT_QUERY = WTS_CONNECTSTATE_CLASS.WTSConnectQuery
DISCONNECTED = WTS_CONNECTSTATE_CLASS.WTSDisconnected
IDLE = WTS_CONNECTSTATE_CLASS.WTSIdle
LISTEN = WTS_CONNECTSTATE_CLASS.WTSListen
SHADOW = WTS_CONNECTSTATE_CLASS.WTSShadow


@pytest.fixture
def detector(tmp_path):
    config = EventLogConfig(
        workstation_id="WS-TEST",
        workstation_hostname="WSTEST",
        agent_version="1.3.0",
    )
    return SessionEventDetector(config, event_queue=EventQueue(config))


def _session(state, session_id: int = 2) -> WTSSessionInfo:
    return WTSSessionInfo(
        session_id=session_id,
        username="becker",
        domain="KIRSCHKE",
        display_name="RDP-Tcp#3",
        client_name="NB12KI",
        connect_state=state,
        protocol_type=2,
    )


@pytest.mark.parametrize(
    ("old_state", "new_state", "expected"),
    [
        (CONNECT_QUERY, ACTIVE, EventType.RDP_LOGON),
        (CONNECT_QUERY, CONNECTED, EventType.RDP_LOGON),
        (ACTIVE, DISCONNECTED, EventType.RDP_DISCONNECT),
        (CONNECTED, DISCONNECTED, EventType.RDP_DISCONNECT),
        (DISCONNECTED, ACTIVE, EventType.RDP_RECONNECT),
        (DISCONNECTED, CONNECTED, EventType.RDP_RECONNECT),
        (ACTIVE, IDLE, EventType.RDP_DISCONNECT),
    ],
)
def test_known_transitions_keep_their_event_type(detector, old_state, new_state, expected) -> None:
    event = detector._create_session_state_change_event(_session(old_state), _session(new_state))
    assert event is not None
    assert event.event_type == expected


@pytest.mark.parametrize(
    ("old_state", "new_state"),
    [
        (ACTIVE, LISTEN),
        (LISTEN, ACTIVE),
        (IDLE, SHADOW),
        (SHADOW, CONNECT_QUERY),
        (CONNECTED, ACTIVE),
        (ACTIVE, CONNECTED),
    ],
)
def test_unmapped_transition_produces_no_event(detector, old_state, new_state) -> None:
    """It must not be recorded as LAUNCH_REQUESTED, which the portal owns."""
    assert detector._create_session_state_change_event(
        _session(old_state), _session(new_state)
    ) is None


def test_no_transition_is_ever_reported_as_launch_requested(detector) -> None:
    states = [ACTIVE, CONNECTED, CONNECT_QUERY, DISCONNECTED, IDLE, LISTEN, SHADOW]
    for old_state in states:
        for new_state in states:
            event = detector._create_session_state_change_event(
                _session(old_state), _session(new_state)
            )
            if event is not None:
                assert event.event_type != EventType.LAUNCH_REQUESTED, (
                    f"{old_state.name} -> {new_state.name}"
                )


@pytest.mark.parametrize(
    ("old_state", "new_state"),
    [(None, ACTIVE), (ACTIVE, None), (None, None)],
)
def test_unknown_connect_state_is_handled_without_attribute_error(
    detector, old_state, new_state
) -> None:
    """connect_state defaults to None when the WTS query fails; .name would crash."""
    assert detector._create_session_state_change_event(
        _session(old_state), _session(new_state)
    ) is None


def test_identical_state_produces_no_event(detector) -> None:
    assert detector._create_session_state_change_event(
        _session(ACTIVE), _session(ACTIVE)
    ) is None


def test_reason_names_both_states(detector) -> None:
    event = detector._create_session_state_change_event(
        _session(ACTIVE), _session(DISCONNECTED)
    )
    assert event is not None
    assert "WTSActive" in event.reason
    assert "WTSDisconnected" in event.reason
