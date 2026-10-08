"""Text, der nicht in seinen Platz passt, wird gekürzt oder bekommt Platz.

Zwei Stellen, an denen Qt Text stillschweigend abschneidet:

* Ein ``QLabel`` ohne Zeilenumbruch verlangt die volle Textbreite als Minimum.
  Steht es in einer Karte fester Breite, reicht der Platz nicht, und das Ende
  fehlt einfach -- ohne Hinweis, dass dort mehr stand. :class:`ElidedLabel`
  kürzt mit „…“ und zeigt den vollen Text im Tooltip.
* ``QMessageBox`` legt seine Breite beim Anzeigen selbst fest und deckelt sie
  bei höchstens 1000 Pixeln, auf kleineren Bildschirmen weniger. Lange
  Knopftexte wurden dann auf beiden Seiten angeschnitten. :func:`fit_message_box`
  gibt dem Fenster nachträglich die Breite, die seine Knöpfe brauchen.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialogButtonBox, QFrame, QLabel, QMessageBox, QWidget


class ElidedLabel(QLabel):
    """Eine Zeile Text, die bei Platzmangel mit „…“ endet statt abzubrechen."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._explicit_tooltip = ""

    def setText(self, text: str) -> None:  # noqa: N802 - Qt-Name
        super().setText(text)
        self._apply_tooltip()

    def setToolTip(self, text: str) -> None:  # noqa: N802 - Qt-Name
        self._explicit_tooltip = text or ""
        self._apply_tooltip()

    def _text_rect_width(self) -> int:
        return self.contentsRect().width() - 2 * self.margin()

    def is_elided(self) -> bool:
        """Ob der Text gerade gekürzt dargestellt wird."""
        text = self.text()
        return bool(text) and self.fontMetrics().horizontalAdvance(text) > self._text_rect_width()

    def _apply_tooltip(self) -> None:
        """Gekürzt steht der volle Text im Tooltip, vor einem eigenen Hinweis."""
        tooltip = self._explicit_tooltip
        if self.is_elided():
            tooltip = f"{self.text()}\n\n{tooltip}" if tooltip else self.text()
        if super().toolTip() != tooltip:
            super().setToolTip(tooltip)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt-Name
        """Schmal genug, dass die Karte die Breite bestimmt und nicht der Text."""
        hint = super().minimumSizeHint()
        width = self.fontMetrics().horizontalAdvance(self.text()[:3] + "…")
        return QSize(min(hint.width(), width + 2 * self.margin()), hint.height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt-Name
        super().resizeEvent(event)
        self._apply_tooltip()

    def event(self, event: QEvent) -> bool:
        # Kurz vor dem Anzeigen noch einmal: Schrift oder Breite können sich
        # seit dem letzten Setzen geändert haben, ohne dass ein Resize kam.
        if event.type() == QEvent.ToolTip:
            self._apply_tooltip()
        return super().event(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt-Name
        if not self.is_elided():
            super().paintEvent(event)
            return
        # Rahmen und Hintergrund aus dem Stylesheet wie sonst auch, nur der
        # Text wird selbst gesetzt -- gekürzt auf die verfügbare Breite.
        QFrame.paintEvent(self, event)
        painter = QPainter(self)
        rect = self.contentsRect().adjusted(
            self.margin(), self.margin(), -self.margin(), -self.margin()
        )
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, rect.width())
        self.style().drawItemText(
            painter, rect, int(self.alignment()), self.palette(), self.isEnabled(),
            text, self.foregroundRole(),
        )
        painter.end()


def fit_message_box(box: QMessageBox) -> None:
    """Das Fenster so breit machen, dass jeder Knopf seinen ganzen Text zeigt.

    Läuft nach dem Anzeigen, weil ``QMessageBox`` seine feste Größe erst dann
    berechnet. Breiter als der Bildschirm wird es nie.
    """
    buttons = box.findChild(QDialogButtonBox)
    layout = box.layout()
    if buttons is None or layout is None:
        return
    margins = layout.contentsMargins()
    needed = buttons.sizeHint().width() + margins.left() + margins.right()
    screen = box.screen()
    if screen is not None:
        needed = min(needed, screen.availableGeometry().width())
    if box.width() < needed:
        box.setFixedWidth(needed)


__all__ = ["ElidedLabel", "fit_message_box"]
