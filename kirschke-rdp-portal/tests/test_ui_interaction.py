from unittest.mock import Mock

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from portal_app.ui.widgets.scroll_safe_combo import ScrollSafeComboBox


def test_closed_combo_forwards_wheel_to_page_without_changing_selection(qtbot):
    scroll = QScrollArea()
    content = QWidget()
    layout = QVBoxLayout(content)
    combo = ScrollSafeComboBox()
    combo.addItems(["A", "B", "C"])
    layout.addWidget(combo)
    layout.addStretch()
    content.setMinimumHeight(1200)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.resize(300, 200)
    qtbot.addWidget(scroll)
    scroll.show()
    scroll.verticalScrollBar().setValue(300)
    before = scroll.verticalScrollBar().value()
    event = Mock()
    event.pixelDelta.return_value = QPoint(0, 0)
    event.angleDelta.return_value = QPoint(0, 120)

    combo.wheelEvent(event)

    assert combo.currentIndex() == 0
    assert scroll.verticalScrollBar().value() < before
    event.accept.assert_called_once()


def test_open_combo_keeps_normal_keyboard_selection(qtbot):
    combo = ScrollSafeComboBox()
    combo.addItems(["A", "B", "C"])
    qtbot.addWidget(combo)
    combo.show()
    combo.showPopup()
    qtbot.keyClick(combo, "B")
    qtbot.keyClick(combo, "\r")
    assert combo.currentText() == "B"
