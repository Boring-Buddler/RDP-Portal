"""Der Umweg, der eine Konsolensitzung abmeldbar macht.

Eine Sitzung am Geraet selbst hat keinen RDP-Client, den Windows dem Agenten
bezeugen koennte -- deshalb lehnt er sie ab. Uebernimmt dieselbe Person die Sitzung
per RDP von hier aus, ist sie danach eine Sitzung dieses Rechners, und dieselbe
Pruefung laesst sie durch. Dieser Dialog wartet nur auf genau diesen Uebergang.
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from portal_app.models.workstation import Workstation
from portal_app.ui.widgets import session_takeover_dialog as takeover
from portal_app.ui.widgets.session_takeover_dialog import SessionTakeoverDialog
from shared.identity import WindowsIdentity

BACKSLASH = chr(92)
ME = "AzureAD" + BACKSLASH + "ChristianBecker"
MY_SID = "S-1-12-1-1-2-3-4"


def accounts():
    return [WindowsIdentity.from_names(ME, sid=MY_SID)]


def snapshot(*sessions):
    return SimpleNamespace(rdp_sessions=list(sessions)), 3


def session(*, name=ME, console=False, state="connected", sid=MY_SID):
    return {
        "session_id": 2,
        "full_username": name,
        "session_state": state,
        "login_time": "2026-09-14T06:00:00+00:00",
        "is_console_session": console,
        "sid": sid,
    }


@pytest.fixture
def dialog(qtbot):
    workstation = Workstation("W1", "NB05", "nb05")
    widget = SessionTakeoverDialog(workstation, accounts())
    qtbot.addWidget(widget)
    widget.timer.stop()  # Der Test taktet selbst.
    return widget


def test_a_console_session_is_not_yet_a_takeover(dialog, monkeypatch):
    monkeypatch.setattr(
        takeover, "request_snapshot", Mock(return_value=snapshot(session(console=True)))
    )

    assert dialog._taken_over() is False


def test_an_own_rdp_session_ends_the_wait(dialog, monkeypatch):
    monkeypatch.setattr(takeover, "request_snapshot", Mock(return_value=snapshot(session())))

    assert dialog._taken_over() is True


def test_somebody_elses_rdp_session_does_not_count(dialog, monkeypatch):
    other = session(name="AzureAD" + BACKSLASH + "Andere", sid="S-1-12-1-9-9-9-9")
    monkeypatch.setattr(takeover, "request_snapshot", Mock(return_value=snapshot(other)))

    assert dialog._taken_over() is False


def test_an_ended_session_does_not_count(dialog, monkeypatch):
    monkeypatch.setattr(
        takeover, "request_snapshot", Mock(return_value=snapshot(session(state="logged_off")))
    )

    assert dialog._taken_over() is False


def test_an_unreachable_agent_is_no_reason_to_give_up(dialog, monkeypatch):
    """Eine einzelne fehlgeschlagene Abfrage bedeutet nichts; der naechste Takt zaehlt."""
    monkeypatch.setattr(takeover, "request_snapshot", Mock(side_effect=OSError("weg")))

    assert dialog._taken_over() is False


def test_the_wait_gives_up_instead_of_running_forever(dialog, monkeypatch):
    monkeypatch.setattr(takeover, "request_snapshot", Mock(return_value=snapshot()))
    dialog.remaining = 0.1

    dialog._check()

    assert not dialog.isVisible() or dialog.cancel.text() == "Schließen"
    assert "nicht als Sitzung dieses Rechners" in dialog.status.text()


def test_a_successful_takeover_accepts_the_dialog(dialog, monkeypatch, qtbot):
    monkeypatch.setattr(takeover, "request_snapshot", Mock(return_value=snapshot(session())))
    finished = []
    dialog.accepted.connect(lambda: finished.append(True))

    dialog._check()

    assert finished == [True]


def test_cancelling_stops_the_polling(dialog):
    dialog.timer.start(1000)

    dialog.reject()

    assert not dialog.timer.isActive()
