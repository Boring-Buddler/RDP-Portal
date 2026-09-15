"""Die Schnellauswahl auf der Maschinenkarte: Aufloesung und alle Monitore.

Beide Werte stehen auch in den Maschinendetails. Auf der Karte liegen sie, weil
es die zwei Angaben sind, die man unmittelbar vor dem Verbinden aendert -- der
Umweg ueber den Bearbeiten-Dialog stand in keinem Verhaeltnis dazu.
"""

import pytest

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.ui.widgets.workstation_cards import (
    CARD_ASPECT,
    CARD_HEIGHT,
    CARD_WIDTH,
    WorkstationCard,
    offered_resolutions,
)


def machine(**kwargs):
    return Workstation("WS-1", "NB12KI", "NB12KI", **kwargs)


@pytest.fixture
def card(qtbot):
    def build(workstation=None):
        widget = WorkstationCard(workstation or machine(), MockUser.create_user())
        qtbot.addWidget(widget)
        return widget

    return build


# --- Format ------------------------------------------------------------------

def test_the_card_keeps_a_four_to_three_format():
    """Ohne feste Breite zog eine einzelne Maschine die Kachel ueber das Fenster."""
    assert CARD_WIDTH == round(CARD_HEIGHT * CARD_ASPECT)
    assert round(CARD_WIDTH / CARD_HEIGHT, 2) == 1.33


def test_the_card_does_not_grow_beyond_that(card):
    widget = card()

    assert widget.maximumWidth() == CARD_WIDTH
    assert widget.minimumWidth() == CARD_WIDTH


# --- Anzeige des gespeicherten Stands ----------------------------------------

def test_a_machine_without_a_resolution_shows_fullscreen(card):
    widget = card()

    assert widget.resolution.currentData() is None
    assert widget.resolution.currentText() == "Vollbild"


def test_a_stored_resolution_is_shown(card):
    widget = card(machine(screen_mode="windowed", resolution="1600x900"))

    assert widget.resolution.currentData() == "1600x900"


def test_a_resolution_without_window_mode_stays_fullscreen(card):
    """Vollbild schlaegt eine hinterlegte Groesse; sonst zeigt die Karte Falsches."""
    widget = card(machine(screen_mode="fullscreen", resolution="1600x900"))

    assert widget.resolution.currentData() is None


def test_an_unusual_size_from_the_details_is_not_lost(card):
    widget = card(machine(screen_mode="windowed", resolution="2560x1440"))

    assert widget.resolution.currentData() == "2560x1440"


def test_the_monitor_choice_is_shown(card):
    assert card(machine(use_all_monitors=True)).all_monitors.isChecked() is True
    assert card().all_monitors.isChecked() is False


def test_loading_a_machine_does_not_look_like_a_change(card, qtbot):
    """Sonst schriebe schon das Aufbauen des Rasters jede Karte zurueck."""
    widget = card()
    seen = []
    widget.display_settings_changed.connect(lambda *args: seen.append(args))

    widget.set_workstation(machine(screen_mode="windowed", resolution="1366x768"), widget.user)

    assert seen == []
    assert widget.resolution.currentData() == "1366x768"


# --- Aenderung meldet sich ---------------------------------------------------

def test_choosing_a_resolution_reports_it(card, qtbot):
    widget = card()

    with qtbot.waitSignal(widget.display_settings_changed) as blocker:
        widget.resolution.setCurrentIndex(widget.resolution.findData("1920x1080"))

    _machine, resolution, all_monitors = blocker.args
    assert resolution == "1920x1080"
    assert all_monitors is False


def test_ticking_all_monitors_reports_it(card, qtbot):
    widget = card()

    with qtbot.waitSignal(widget.display_settings_changed) as blocker:
        widget.all_monitors.setChecked(True)

    assert blocker.args[2] is True


# --- Angebotene Auflösungen ---------------------------------------------------

def values(native):
    return [value for _, value in offered_resolutions(native)]


def test_a_4k_screen_is_offered_everything():
    assert "3840x2160" in values((3840, 2160))
    assert "2560x1440" in values((3840, 2160))


def test_nothing_larger_than_the_screen_is_offered():
    """Eine Sitzung über der Panelgröße ist nur noch durch Scrollen erreichbar."""
    offered = values((1920, 1080))

    assert "3840x2160" not in offered
    assert "2560x1440" not in offered
    assert "1920x1080" in offered


def test_the_screens_own_size_becomes_the_maximum():
    """Bei einem krummen Panel wäre sonst 1920x1080 das Größte -- unter der Auflösung."""
    offered = offered_resolutions((2256, 1504))

    assert offered[1] == ("2256 x 1504 (Bildschirm)", "2256x1504")


def test_a_standard_size_is_not_listed_twice():
    offered = values((1920, 1080))

    assert offered.count("1920x1080") == 1


def test_fullscreen_is_always_first():
    for native in ((1280, 720), (1920, 1080), (3840, 2160)):
        assert offered_resolutions(native)[0] == ("Vollbild", None)


def test_an_unreadable_screen_offers_the_full_list(monkeypatch):
    monkeypatch.setattr(
        "portal_app.ui.widgets.workstation_cards.native_screen_size", lambda: None
    )

    assert "3840x2160" in [value for _, value in offered_resolutions()]


def test_a_larger_size_configured_elsewhere_is_not_lost(card, monkeypatch):
    """Eine 4K-Maschine darf ihre Einstellung nicht verlieren, nur weil dieser
    Bildschirm kleiner ist."""
    monkeypatch.setattr(
        "portal_app.ui.widgets.workstation_cards.offered_resolutions",
        lambda native=None: offered_resolutions((1920, 1080)),
    )
    widget = card(machine(screen_mode="windowed", resolution="3840x2160"))

    assert widget.resolution.currentData() == "3840x2160"
