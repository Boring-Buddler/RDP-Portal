"""Combo box that does not change a closed selection while a page is scrolled."""

from PySide6.QtWidgets import QAbstractScrollArea, QComboBox


class ScrollSafeComboBox(QComboBox):
    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QAbstractScrollArea):
            parent = parent.parentWidget()
        if isinstance(parent, QAbstractScrollArea):
            delta = event.pixelDelta().y() or event.angleDelta().y()
            bar = parent.verticalScrollBar()
            step = abs(delta) if event.pixelDelta().y() else bar.singleStep() * 3
            bar.setValue(bar.value() - (step if delta > 0 else -step))
        event.accept()

__all__ = ["ScrollSafeComboBox"]
