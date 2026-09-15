"""Waehrend einer Abmeldung wird die Maschine nicht live abgefragt.

Der Agent hat genau eine Pipe-Instanz und bedient sie seriell. LOGOFF/1 belegt sie,
bis Windows die Sitzung abgebaut hat -- dafuer steht LOGOFF_TIMEOUT_MS. Jede
STATUS/1-Abfrage dorthin muss in dieser Zeit in den Timeout laufen. Ohne Pause haette
das Portal die Maschine als "Agent nicht erreichbar" gezeigt, genau waehrend der
Benutzer der Abmeldung zusieht, und danach noch den Backoff der Live-Abfrage geerbt.
"""

from unittest.mock import Mock

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore


def machine(identifier):
    return Workstation(workstation_id=identifier, display_name=identifier, hostname=identifier)


@pytest.fixture
def window(tmp_path, monkeypatch, qtbot):
    from portal_app.ui.main_window import MainWindow

    store = LocalStore(tmp_path / "state.json")
    store.save([machine("WS-1"), machine("WS-2")], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    widget = MainWindow(automatic_live_status=False)
    qtbot.addWidget(widget)
    # Der Datei-Fallback gehoert nicht zu dieser Frage und liest sonst echte Ordner.
    monkeypatch.setattr(widget, "_poll_agent_status", Mock())
    widget.live_status_poller.request_many = Mock(return_value=0)
    return widget


def polled_ids(widget):
    targets, *_ = widget.live_status_poller.request_many.call_args.args
    return [item.workstation_id for item in targets]


def test_a_machine_being_logged_off_is_not_polled(window):
    window._logoff_in_progress.add("WS-1")

    window._run_status_update_cycle(force=True)

    assert polled_ids(window) == ["WS-2"]


def test_every_other_machine_is_still_polled(window):
    window._logoff_in_progress.add("WS-1")

    window._run_status_update_cycle([window.workstations[1]], force=True)

    assert polled_ids(window) == ["WS-2"]


def test_without_a_running_logoff_nothing_is_held_back(window):
    window._run_status_update_cycle(force=True)

    assert polled_ids(window) == ["WS-1", "WS-2"]


def test_a_finished_logoff_releases_the_pause_and_refreshes(window):
    target = window.workstations[0]
    window._logoff_in_progress.add(target.workstation_id)

    window._own_logoff_finished(target, True)

    assert target.workstation_id not in window._logoff_in_progress
    assert polled_ids(window) == ["WS-1"]


def test_a_failed_logoff_also_releases_the_pause(window):
    """Sonst bliebe die Maschine dauerhaft von der Live-Abfrage ausgenommen."""
    target = window.workstations[0]
    window._logoff_in_progress.add(target.workstation_id)

    window._own_logoff_finished(target, False)

    assert target.workstation_id not in window._logoff_in_progress
    window.live_status_poller.request_many.assert_not_called()
