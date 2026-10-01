"""Jeder ordnet die Maschinenkarten für sich selbst an.

Die Anordnung ist eine Angewohnheit, keine Eigenschaft der Maschinen: Sie liegt
deshalb in der Benutzerdatei und nicht im gemeinsamen Stand. Würde sie geteilt,
legte der Letzte, der eine Karte verschiebt, die Anordnung für alle fest.

Der Zustand sortiert nirgends mit: Eine Kachel merkt man sich über ihren Platz,
und der muss deshalb stillhalten. Wer nichts verschoben hat, bekommt die
Maschinen nach Namen; wer verschiebt, bekommt seine eigene Anordnung.

Verschoben wird nur über den Griff unter den Knöpfen. Die Karte selbst nimmt
kein Ziehen entgegen -- ein Druck auf sie öffnet die Maschinenseite.
"""

import json

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from portal_app.services.local_store import LocalStore
from portal_app.ui.widgets.workstation_cards import (
    CARD_MIME_TYPE,
    WorkstationCard,
    WorkstationCardsWidget,
    card_gap,
    card_height,
    card_width,
)
from shared.enums import AgentStatus, SessionState


def machine(identifier: str, name: str, state: SessionState = SessionState.NONE) -> Workstation:
    workstation = Workstation(
        identifier, name, name.upper(),
        agent_status=AgentStatus.ONLINE,
        current_session_state=state,
        current_session_user="OTHER\\kollege" if state != SessionState.NONE else None,
    )
    workstation.agent_status_source = "live"
    return workstation


@pytest.fixture
def dashboard(qtbot):
    def build(machines=None):
        machines = machines or [
            machine("WS-1", "Alpha", SessionState.CONNECTED),
            machine("WS-2", "Beta"),
            machine("WS-3", "Gamma"),
        ]
        widget = WorkstationCardsWidget(machines, MockUser.create_user())
        qtbot.addWidget(widget)
        # Ohne einen echten Layoutdurchlauf haben alle Karten dieselbe
        # Vorgabegeometrie, und die Treffpruefung beim Ablegen faende immer die
        # erste. Breit genug fuer eine Reihe, damit auch links/rechts zaehlt.
        widget.resize(card_width() * 3 + card_gap() * 4, card_height() * 2)
        # Der Rasterbehaelter bekommt seine Groesse sonst erst beim Anzeigen,
        # und ein gestauchtes Raster laesst die Karten einander ueberlappen.
        widget.grid_host.resize(widget.width(), card_height() * 3)
        widget.grid.activate()
        return widget

    return build


def visible(widget) -> list[str]:
    return [
        card.workstation.workstation_id
        for card in widget._cards
        if isinstance(card, WorkstationCard)
    ]


# --- Vorgabe ohne eigene Reihenfolge -----------------------------------------


def test_without_a_personal_order_machines_are_sorted_by_name(dashboard):
    """Eine Anordnung, die sich von selbst nicht ändert."""
    widget = dashboard()

    # Alpha ist belegt und steht trotzdem vorn: Der Zustand sortiert nicht mit.
    assert visible(widget) == ["WS-1", "WS-2", "WS-3"]


def test_the_default_order_holds_when_a_machine_changes_state(dashboard):
    """Der eigentliche Zweck: Keine Karte wandert, weil sich jemand verbindet."""
    machines = [machine("WS-1", "Alpha"), machine("WS-2", "Beta"), machine("WS-3", "Gamma")]
    widget = dashboard(machines)
    before = visible(widget)

    machines[0].current_session_state = SessionState.CONNECTED
    machines[0].current_session_user = "OTHER\\kollege"
    widget.set_workstations(machines)

    assert visible(widget) == before


def test_no_reset_button_is_shown(dashboard):
    widget = dashboard()

    assert not hasattr(widget, "reset_order_button")


# --- Mit eigener Reihenfolge -------------------------------------------------


def test_a_personal_order_wins_over_the_state(dashboard):
    widget = dashboard()

    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])

    assert visible(widget) == ["WS-1", "WS-2", "WS-3"]


def test_the_order_holds_when_a_machine_changes_state(dashboard):
    """Der eigentliche Zweck: Die Karte bleibt, wo man sie hingelegt hat."""
    machines = [machine("WS-1", "Alpha"), machine("WS-2", "Beta"), machine("WS-3", "Gamma")]
    widget = dashboard(machines)
    widget.set_machine_order(["WS-3", "WS-1", "WS-2"])

    machines[2].current_session_state = SessionState.CONNECTED
    machines[2].current_session_user = "OTHER\\kollege"
    widget.set_workstations(machines)

    assert visible(widget) == ["WS-3", "WS-1", "WS-2"]


def test_a_new_machine_lands_at_the_end_without_displacing_anything(dashboard):
    machines = [machine("WS-1", "Alpha"), machine("WS-2", "Beta")]
    widget = dashboard(machines)
    widget.set_machine_order(["WS-2", "WS-1"])

    widget.set_workstations([*machines, machine("WS-9", "Neu")])

    assert visible(widget) == ["WS-2", "WS-1", "WS-9"]


def test_an_order_naming_an_unknown_machine_does_no_harm(dashboard):
    """Eine gelöschte Maschine darf die Anordnung der übrigen nicht kippen."""
    widget = dashboard()

    widget.set_machine_order(["WS-GELOESCHT", "WS-3", "WS-1", "WS-2"])

    assert visible(widget) == ["WS-3", "WS-1", "WS-2"]


def test_no_reset_button_is_shown_with_personal_order(dashboard):
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])
    assert not hasattr(widget, "reset_order_button")
    assert visible(widget) == ["WS-1", "WS-2", "WS-3"]


# --- Ablegen einer gezogenen Karte -------------------------------------------


def drop_at(widget, workstation_id: str, point: QPoint) -> list[str] | None:
    """Ein Ablegen nachstellen und die gemeldete Reihenfolge zurückgeben."""
    received: list[list[str]] = []
    widget.order_changed.connect(received.append)
    widget._on_card_dropped(workstation_id, point)
    return received[0] if received else None


def lay_out(widget) -> None:
    """Das Raster tatsächlich auslegen lassen.

    Jedes Neuaufbauen erzeugt neue Karten, und die tragen bis zum nächsten
    Layoutdurchlauf alle dieselbe Vorgabegeometrie. Im laufenden Fenster
    passiert das von selbst, hier nicht -- und ohne echte Geometrien prüft die
    Treffsuche beim Ablegen nichts.
    """
    widget.grid_host.resize(widget.width(), card_height() * 4)
    widget.grid.activate()


def handle_of(widget, workstation_id: str) -> tuple:
    """Den Griff einer Karte samt Mitschrift seiner Zugmeldungen.

    Die eigene Verbindung der Karte wird dabei geloest -- und das ist zugleich
    die Probe darauf, dass sie besteht: ``QDrag.exec`` uebernimmt sonst die
    Maus und kehrt ohne eine solche nie zurueck.
    """
    card = card_for(widget, workstation_id)
    card.drag_handle.drag_requested.disconnect(card._start_drag)
    requested: list = []
    card.drag_handle.drag_requested.connect(lambda: requested.append(True))
    return card.drag_handle, requested


def press_on(widget) -> QMouseEvent:
    """Ein Druck der linken Taste in der Mitte des Widgets."""
    return _mouse_event(QEvent.MouseButtonPress, QPointF(widget.rect().center()))


def move_on(widget, offset: QPoint) -> QMouseEvent:
    """Eine Bewegung um ``offset`` weg von der Mitte, Taste weiter gedrueckt."""
    return _mouse_event(
        QEvent.MouseMove, QPointF(widget.rect().center() + offset)
    )


def _mouse_event(kind, position: QPointF) -> QMouseEvent:
    return QMouseEvent(
        kind, position, position, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )


def card_for(widget, workstation_id: str) -> WorkstationCard:
    return next(
        card
        for card in widget._cards
        if isinstance(card, WorkstationCard)
        and card.workstation.workstation_id == workstation_id
    )


def test_dropping_on_the_left_half_inserts_before(dashboard):
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])
    lay_out(widget)
    target = card_for(widget, "WS-2").geometry()

    order = drop_at(widget, "WS-3", QPoint(target.left() + 5, target.center().y()))

    assert order == ["WS-1", "WS-3", "WS-2"]


def test_dropping_on_the_right_half_inserts_after(dashboard):
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])
    lay_out(widget)
    target = card_for(widget, "WS-1").geometry()

    order = drop_at(widget, "WS-3", QPoint(target.right() - 5, target.center().y()))

    assert order == ["WS-1", "WS-3", "WS-2"]


def test_dropping_into_the_empty_space_at_the_end_appends(dashboard):
    """Hinter der letzten Karte ist freier Platz, und dort wird abgelegt."""
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])
    lay_out(widget)

    order = drop_at(widget, "WS-1", QPoint(20000, 20000))

    assert order == ["WS-2", "WS-3", "WS-1"]


def test_dropping_into_the_gap_between_two_cards_still_counts(dashboard):
    """Zwischen den Karten liegen Abstände -- eine Ablage dort traf vorher nichts."""
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3"])
    lay_out(widget)
    first = card_for(widget, "WS-1").geometry()
    second = card_for(widget, "WS-2").geometry()
    gap = QPoint(
        (first.right() + second.left()) // 2,
        (first.center().y() + second.center().y()) // 2,
    )

    order = drop_at(widget, "WS-3", gap)

    assert order in (["WS-1", "WS-3", "WS-2"], ["WS-3", "WS-1", "WS-2"])
    assert order != ["WS-1", "WS-2", "WS-3"]


def test_the_first_drag_pins_the_whole_visible_order(dashboard):
    """Gespeichert wird die ganze Reihenfolge, nicht nur die bewegte Karte."""
    widget = dashboard()  # Ohne eigene Reihenfolge: WS-1, WS-2, WS-3
    lay_out(widget)
    target = card_for(widget, "WS-1").geometry()

    order = drop_at(widget, "WS-3", QPoint(target.left() + 5, target.center().y()))

    assert order == ["WS-3", "WS-1", "WS-2"]


def test_a_hidden_machine_keeps_its_place(dashboard):
    """Ein gesetzter Filter darf die Anordnung der Ausgeblendeten nicht verwerfen."""
    widget = dashboard()
    widget.set_machine_order(["WS-1", "WS-2", "WS-3", "WS-VERSTECKT"])
    lay_out(widget)
    target = card_for(widget, "WS-1").geometry()

    order = drop_at(widget, "WS-2", QPoint(target.left() + 5, target.center().y()))

    assert order == ["WS-2", "WS-1", "WS-3", "WS-VERSTECKT"]


# --- Der Griff ---------------------------------------------------------------


def test_only_the_handle_carries_the_grabbing_cursor(dashboard):
    """Die greifende Hand sagt, wo sich die Karte anfassen laesst."""
    widget = dashboard()
    card = card_for(widget, "WS-2")

    assert card.drag_handle.cursor().shape() == Qt.OpenHandCursor
    assert card.cursor().shape() == Qt.PointingHandCursor


def test_the_handle_sits_below_the_connect_button(dashboard):
    widget = dashboard()
    card = card_for(widget, "WS-2")
    # Ohne einen Layoutdurchlauf sitzt auf der Karte noch alles bei y = 0.
    card.layout().activate()

    assert card.drag_handle.y() > card.connect_btn.y()


def test_pressing_the_handle_does_not_open_the_machine_page(dashboard):
    """Sonst waere die Seite offen, bevor das Ziehen ueberhaupt beginnt."""
    widget = dashboard()
    card = card_for(widget, "WS-2")
    opened: list = []
    card.selected.connect(opened.append)

    card.drag_handle.mousePressEvent(press_on(card.drag_handle))

    assert opened == []
    assert card.drag_handle.cursor().shape() == Qt.ClosedHandCursor


def test_pressing_the_card_itself_opens_the_machine_page(dashboard):
    """Die Karte bleibt der Weg zur Maschinenseite."""
    widget = dashboard()
    card = card_for(widget, "WS-2")
    opened: list = []
    card.selected.connect(opened.append)

    card.mousePressEvent(press_on(card))

    assert [item.workstation_id for item in opened] == ["WS-2"]


def test_a_short_wobble_on_the_handle_moves_nothing(dashboard):
    """Unterhalb der Systemschwelle ist das ein Klick, kein Ziehen."""
    widget = dashboard()
    handle, requested = handle_of(widget, "WS-2")

    handle.mousePressEvent(press_on(handle))
    handle.mouseMoveEvent(move_on(handle, QPoint(1, 0)))

    assert requested == []


def test_dragging_the_handle_far_enough_starts_the_move(dashboard):
    widget = dashboard()
    handle, requested = handle_of(widget, "WS-2")

    handle.mousePressEvent(press_on(handle))
    handle.mouseMoveEvent(
        move_on(handle, QPoint(QApplication.startDragDistance() + 5, 0))
    )

    assert requested == [True]


def test_the_drag_payload_uses_an_own_type(dashboard):
    """Damit das Raster nicht jede Datei annimmt, die jemand hineinzieht.

    Der Zug selbst wird hier nicht ausgeloest: ``QDrag.exec`` uebernimmt die
    Maus und kehrt ohne eine solche nicht zurueck.
    """
    widget = dashboard()
    card = card_for(widget, "WS-2")

    assert CARD_MIME_TYPE.startswith("application/x-kirschke")
    assert card.workstation.workstation_id == "WS-2"


# --- Speicherung -------------------------------------------------------------


def test_the_order_is_personal_and_not_shared(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()
    store.save([machine("WS-1", "Alpha")], user, [])

    store.save_machine_order(["WS-2", "WS-1"], user)

    shared = json.loads(store.path.read_text(encoding="utf-8"))
    personal = json.loads(store.preferences_path.read_text(encoding="utf-8"))
    assert "machine_order" not in shared
    assert personal["machine_order"] == ["WS-2", "WS-1"]


def test_the_order_survives_a_restart(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()
    store.save([machine("WS-1", "Alpha")], user, [])
    store.save_machine_order(["WS-2", "WS-1"], user)

    reopened = LocalStore(store.path)
    reopened.load([], user)

    assert reopened.machine_order == ["WS-2", "WS-1"]


def test_duplicates_and_blanks_are_dropped(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()
    store.save([machine("WS-1", "Alpha")], user, [])

    assert store.save_machine_order(["WS-1", "  ", "ws-1", "WS-2"], user) == ["WS-1", "WS-2"]


def test_an_empty_order_restores_sorting_by_state(tmp_path):
    store = LocalStore(tmp_path / "portal-state.json")
    user = MockUser.create_user()
    store.save([machine("WS-1", "Alpha")], user, [])
    store.save_machine_order(["WS-2", "WS-1"], user)

    assert store.save_machine_order([], user) == []
    assert LocalStore(store.path).load([], user) and LocalStore(store.path).machine_order == []
