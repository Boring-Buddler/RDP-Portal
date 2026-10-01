"""Die Oberfläche folgt der Windows-Einstellung für Schriftgröße.

Zwei Dinge gingen vorher schief. Erstens standen die Schriftgrößen als feste
Punktzahlen in den Stylesheets und überschrieben die Anwendungsschrift -- wer in
Windows eine größere Schrift eingestellt hatte, bekam sie überall außer im
Portal. Zweitens waren Karten, Knöpfe und Fenster in festen Pixeln bemessen: Mit
größerer Schrift stand der Text halb außerhalb, und ein Mindestmaß von
1080 x 720 passte bei 150 % Anzeigeskalierung nicht mehr auf einen
1920 x 1080-Schirm.
"""

import pytest

from portal_app.ui import design
from portal_app.ui.design import (
    MAX_POINT_SIZE,
    MIN_POINT_SIZE,
    REFERENCE_POINT_SIZE,
    Typography,
    scale_factor,
    scale_stylesheet,
    scaled,
    scaled_points,
)


@pytest.fixture
def at_point_size(monkeypatch):
    """Tut so, als hätte Windows diese Schriftgröße vorgegeben."""

    def apply(points: float | None):
        monkeypatch.setattr(design, "_system_point_size", points)

    return apply


# --- Der Faktor --------------------------------------------------------------


def test_the_design_size_scales_nothing(at_point_size):
    at_point_size(REFERENCE_POINT_SIZE)

    assert scale_factor() == 1.0
    assert scaled(384) == 384


def test_a_larger_system_font_enlarges_the_measurements(at_point_size):
    at_point_size(12.0)

    assert scale_factor() == pytest.approx(4 / 3)
    assert scaled(384) == 512
    assert scaled_points(9) == 12.0


def test_an_absurd_system_size_is_clamped(at_point_size, monkeypatch):
    """Eine Zwei-Punkt-Schrift macht das Fenster nicht benutzbarer."""
    from PySide6.QtGui import QFont

    for reported, expected in ((2.0, MIN_POINT_SIZE), (40.0, MAX_POINT_SIZE)):
        at_point_size(None)
        font = QFont()
        font.setPointSizeF(reported)
        monkeypatch.setattr(design.QFontDatabase, "systemFont", lambda _kind, f=font: f)
        assert design.system_point_size() == expected


def test_an_unreadable_system_size_falls_back_to_the_design(at_point_size, monkeypatch):
    from PySide6.QtGui import QFont

    at_point_size(None)
    font = QFont()
    font.setPixelSize(16)  # pointSizeF() liefert dann -1.
    monkeypatch.setattr(design.QFontDatabase, "systemFont", lambda _kind, f=font: f)

    assert design.system_point_size() == REFERENCE_POINT_SIZE


def test_a_measurement_never_collapses_to_nothing(at_point_size):
    at_point_size(MIN_POINT_SIZE)

    assert scaled(1) >= 1


# --- Stylesheets -------------------------------------------------------------


def test_font_sizes_in_stylesheets_follow_along(at_point_size):
    at_point_size(12.0)

    result = scale_stylesheet("QLabel#cardMeta { color: #526572; font-size: 9pt; }")

    assert "font-size: 12.0pt" in result


def test_minimum_heights_grow_with_the_font(at_point_size):
    """Sonst schneidet ein Feld fester Mindesthöhe die größere Schrift ab."""
    at_point_size(12.0)

    result = scale_stylesheet("QWizard QLineEdit { min-height: 22px; min-width: 82px; }")

    assert "min-height: 29px" in result
    assert "min-width: 109px" in result


def test_colours_and_paddings_are_left_alone(at_point_size):
    """Nur was mit der Schrift wachsen muss -- eine Randfarbe gehört nicht dazu."""
    at_point_size(12.0)
    css = "QFrame { background: #ffffff; border-radius: 14px; padding: 6px 12px; }"

    assert scale_stylesheet(css) == css


def test_at_the_design_size_the_stylesheet_is_untouched(at_point_size):
    at_point_size(REFERENCE_POINT_SIZE)
    css = "QLabel { font-size: 9pt; min-height: 22px; }"

    assert scale_stylesheet(css) == css


# --- Schriften ---------------------------------------------------------------


def test_the_body_font_uses_the_system_size(qapp, at_point_size):
    at_point_size(12.0)

    assert Typography.body().pointSizeF() == pytest.approx(12.0)


def test_the_relative_steps_are_kept(qapp, at_point_size):
    """Eine Überschrift bleibt eine Überschrift, auch skaliert."""
    at_point_size(12.0)

    assert Typography.heading_1().pointSizeF() > Typography.body().pointSizeF()
    assert Typography.body_small().pointSizeF() < Typography.body().pointSizeF()


# --- Fenstergeometrie --------------------------------------------------------


def test_a_window_never_demands_more_than_the_screen_offers(qtbot, at_point_size):
    """Der Fall, der ein Fenster unbedienbar macht: Mindestmaß größer als der Schirm."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QWidget

    at_point_size(MAX_POINT_SIZE)
    widget = QWidget()
    qtbot.addWidget(widget)

    design.apply_scaled_geometry(widget, (1080, 720), (1360, 860))

    available = QGuiApplication.primaryScreen().availableGeometry()
    assert widget.minimumWidth() <= available.width()
    assert widget.minimumHeight() <= available.height()
    assert widget.width() >= widget.minimumWidth()


def test_a_window_grows_with_the_font_while_it_fits(qtbot, at_point_size):
    from PySide6.QtWidgets import QWidget

    at_point_size(REFERENCE_POINT_SIZE)
    small = QWidget()
    qtbot.addWidget(small)
    design.apply_scaled_geometry(small, (300, 200))

    at_point_size(12.0)
    large = QWidget()
    qtbot.addWidget(large)
    design.apply_scaled_geometry(large, (300, 200))

    assert large.minimumWidth() > small.minimumWidth()


# --- Karten ------------------------------------------------------------------


def test_the_card_grid_counts_columns_with_the_width_it_actually_draws(qapp, at_point_size, monkeypatch):
    """Sonst bleibt je Reihe eine Karte Platz ungenutzt oder eine zu viel gedrängt."""
    from portal_app.ui.widgets import workstation_cards as cards

    at_point_size(12.0)
    monkeypatch.setattr(cards, "_screen_width_limit", lambda: 0)

    assert cards.card_width() == scaled(cards.CARD_WIDTH)
    assert cards.card_height() == scaled(cards.CARD_HEIGHT)
    assert cards.card_gap() == scaled(cards.CARD_GAP)


def test_a_card_never_grows_wider_than_the_screen(qapp, at_point_size, monkeypatch):
    """Eine Karte breiter als das Fenster erzwingt waagerechtes Scrollen.

    Genau dorthin führt eine sehr große Systemschrift auf einem kleinen
    Bildschirm: Bei 16 Punkt wäre die Karte 910 Pixel breit und passte in ein
    Fenster von 760 nicht mehr hinein.
    """
    from portal_app.ui.widgets import workstation_cards as cards

    at_point_size(16.0)
    monkeypatch.setattr(cards, "_screen_width_limit", lambda: 600)

    width, height = cards.card_size()

    assert width == 600
    # Das Seitenverhältnis bleibt -- eine nur in der Breite gestutzte Karte
    # sähe neben den anderen wie ein Fehler aus.
    assert height == round(600 / cards.CARD_ASPECT)


def test_an_unclamped_card_keeps_its_four_to_three_format(qapp, at_point_size, monkeypatch):
    from portal_app.ui.widgets import workstation_cards as cards

    at_point_size(12.0)
    monkeypatch.setattr(cards, "_screen_width_limit", lambda: 100000)

    width, height = cards.card_size()

    assert round(width / height, 2) == 1.33
