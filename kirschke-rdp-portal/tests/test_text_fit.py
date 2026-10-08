"""Kein sichtbarer Text wird abgeschnitten -- auch nicht bei größerer Schrift.

Gemeldet waren drei Stellen: Knöpfe einer Rückfrage, deren Beschriftung links
und rechts fehlte; Auswahlfelder auf den Karten, deren Text unten abgeschnitten
war; Filterfelder, deren Text mitten im Wort endete. Alle drei hatten dieselbe
Ursache: feste Maße, die bei größerer Windows-Schrift oder einem kleinen
Fenster nicht mehr reichten.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from portal_app.ui import design
from portal_app.ui.text_fit import ElidedLabel, fit_message_box
from portal_app.ui.widgets.flow_layout import FlowLayout

BS = chr(92)


# --- Bausteine ---------------------------------------------------------------


def test_a_long_label_is_shortened_and_keeps_its_text_in_the_tooltip(qtbot):
    label = ElidedLabel("Berechnungs-Workstation Hamburg Süd, zweites Obergeschoss")
    qtbot.addWidget(label)
    label.show()
    label.resize(80, 20)

    assert label.is_elided()
    assert label.text().startswith("Berechnungs-Workstation")
    assert label.toolTip().startswith("Berechnungs-Workstation")


def test_a_label_that_fits_keeps_its_own_tooltip(qtbot):
    label = ElidedLabel("Kurz")
    label.setToolTip("Hinweis")
    qtbot.addWidget(label)
    label.show()
    label.resize(400, 20)

    assert not label.is_elided()
    assert label.toolTip() == "Hinweis"


def test_a_shortened_label_shows_its_text_before_its_own_tooltip(qtbot):
    label = ElidedLabel("Agent: Online · Verbunden · Live seit gerade eben")
    label.setToolTip("Diagnose")
    qtbot.addWidget(label)
    label.show()
    label.resize(60, 20)

    assert label.toolTip() == f"{label.text()}\n\nDiagnose"


def test_the_label_does_not_force_its_width_on_the_layout(qtbot):
    label = ElidedLabel("x" * 200)
    qtbot.addWidget(label)

    assert label.minimumSizeHint().width() < label.sizeHint().width() / 4


def test_message_box_buttons_get_their_full_width(qtbot):
    box = QMessageBox()
    qtbot.addWidget(box)
    box.setText("Kurz.")
    for text in ("Eintrag entfernen und verbinden", "Gespeichertes Konto nutzen"):
        box.addButton(text, QMessageBox.AcceptRole)
    box.addButton(QMessageBox.Cancel)
    box.show()
    box.setFixedWidth(200)  # so schmal, wie QMessageBox es sich selbst ausgesucht hätte

    fit_message_box(box)

    for button in box.buttons():
        assert button.width() >= button.sizeHint().width()


def test_a_flow_layout_wraps_instead_of_squeezing(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host)
    buttons = [QPushButton(f"Ein recht langer Knopf {index}") for index in range(4)]
    for button in buttons:
        flow.addWidget(button)
    widest = max(button.sizeHint().width() for button in buttons)
    host.resize(widest + 20, flow.heightForWidth(widest + 20))
    host.show()

    for button in buttons:
        assert button.width() == button.sizeHint().width()
    assert len({button.y() for button in buttons}) == 4


def test_a_right_aligned_flow_ends_at_the_right_edge(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    flow = FlowLayout(host, align_right=True)
    button = QPushButton("Speichern")
    flow.addWidget(button)
    host.resize(400, 60)
    host.show()

    assert button.geometry().right() == host.contentsRect().right()


# --- Das ganze Fenster -------------------------------------------------------


def _needed(widget: QWidget) -> tuple[int, int]:
    hint = widget.sizeHint()
    if isinstance(widget, QComboBox) and widget.count():
        metrics = widget.fontMetrics()
        widest = max(metrics.horizontalAdvance(widget.itemText(i)) for i in range(widget.count()))
        return hint.width() - widest + metrics.horizontalAdvance(widget.currentText()), hint.height()
    if isinstance(widget, QLabel) and widget.wordWrap():
        return 0, widget.heightForWidth(widget.width())
    return hint.width(), hint.height()


def clipped_widgets(root: QWidget) -> list[str]:
    """Sichtbare Texte, deren Platz kleiner ist als der Text selbst."""
    problems = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, (QLabel, QPushButton, QCheckBox, QComboBox)):
            continue
        if not widget.isVisibleTo(root) or widget.width() <= 0:
            continue
        if isinstance(widget, QComboBox):
            text = widget.currentText()
        elif isinstance(widget, (QLabel, QAbstractButton)):
            text = widget.text()
        else:
            text = ""
        if not text.strip() or text.strip() == "●":
            continue
        if getattr(widget, "is_elided", None) is not None:
            continue  # kürzt selbst mit „…“ und zeigt den Rest im Tooltip
        need_width, need_height = _needed(widget)
        if need_width - widget.width() > 1 or need_height - widget.height() > 1:
            problems.append(
                f"{type(widget).__name__}#{widget.objectName()} {text[:40]!r}: "
                f"{widget.width()}x{widget.height()}, braucht {need_width}x{need_height}"
            )
    return problems


def _machines(user):
    from portal_app.models.workstation import Workstation
    from shared.enums import AgentStatus, SessionState

    specs = [
        ("WS-1", "Remote-Ettlingen", "disconnected", "AzureAD" + BS + "HendrikSchälikeAdmin"),
        ("WS-2", "NB13KI", "connected", "NB13KI" + BS + "Josch"),
        ("WS-3", "PC12 CB", None, None),
        ("WS-4", "Berechnungs-Workstation Hamburg Süd", "disconnected", "NB12KI" + BS + "Codex"),
    ]
    machines = []
    for workstation_id, name, state, account in specs:
        machine = Workstation(workstation_id, name, name.split()[0], site="Ettlingen",
                              description="Workstation")
        machine.agent_status = AgentStatus.ONLINE
        machine.agent_status_source = "live"
        machine.login_accounts = ["NB12KI" + BS + "Codex", "AzureAD" + BS + "becker@prof-kirschke.de"]
        if state:
            domain, _, name_part = account.partition(BS)
            machine.current_session_state = SessionState(state)
            machine.current_session_user = account
            machine.agent_sessions = [{
                "session_id": 2, "username": name_part, "domain": domain,
                "full_username": account, "session_state": state,
                "login_time": "2026-10-06T07:00:00+00:00", "is_console_session": False,
            }]
        machines.append(machine)
    # Eigene Sitzung: Karte mit dem dicken Rand, bei dem es zuerst eng wurde.
    user.claim_account(specs[3][3])
    return machines


@pytest.mark.parametrize("points", [9.0, 12.0])
def test_no_page_cuts_off_text_in_a_small_window(qtbot, monkeypatch, tmp_path, points):
    """1280 x 720 ist ein Full-HD-Bildschirm bei 150 % Anzeigeskalierung."""
    from portal_app.models.user import MockUser
    from portal_app.services.local_store import LocalStore
    from portal_app.ui.main_window import MainWindow

    monkeypatch.setattr(design, "_system_point_size", points)
    store = LocalStore(tmp_path / "inventory" / "portal-state.json")
    store.save([], MockUser.create_user(), [])
    monkeypatch.setattr("portal_app.ui.main_window.LocalStore", lambda: store)
    for kind in ("information", "warning"):
        monkeypatch.setattr(f"portal_app.ui.main_window.QMessageBox.{kind}", lambda *a, **k: None)

    window = MainWindow(automatic_live_status=False)
    qtbot.addWidget(window)
    window.workstations = _machines(window.current_user)
    window.overview_view.favorites_filter.setChecked(False)
    window.show()
    window.resize(1280, 720)
    window._refresh_workstation_views()

    pages = {
        "Maschinen": window._show_machines,
        "Kalender": lambda: window.stack.setCurrentWidget(window.calendar_view),
        "Admin": lambda: window.stack.setCurrentWidget(window.admin_view),
        "Einstellungen": lambda: window.stack.setCurrentWidget(window.settings_view),
        "Logs": lambda: window.stack.setCurrentWidget(window.session_log_view),
        "Details": lambda: window.on_workstation_selected(window.workstations[0]),
        "Liste": lambda: (window._show_machines(),
                          window.overview_view.set_machine_view("list")),
    }
    problems = []
    for name, show in pages.items():
        show()
        qtbot.wait(50)
        problems += [f"{name}: {line}" for line in clipped_widgets(window)]

    assert problems == []
