"""Ein Layout, das umbricht, wenn die Zeile voll ist.

Die Filterleiste der Maschinenübersicht stand in einer festen Zeile mit fest
bemessenen Auswahlfeldern. Bei größerer Windows-Schrift passten die Texte nicht
mehr in die Felder; mit Feldern, die mit ihrem Text wachsen, passte dann die
Zeile nicht mehr ins Fenster. Hier rutscht, was nicht mehr passt, in die
nächste Zeile -- jedes Feld behält seine volle Breite.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Ordnet Elemente nebeneinander an und bricht bei Platzmangel um."""

    def __init__(
        self, parent: QWidget | None = None, spacing: int = 10, *, align_right: bool = False
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        #: Jede Zeile rechtsbündig -- für Knopfgruppen, die rechts stehen.
        self.align_right = align_right
        self.setContentsMargins(QMargins(0, 0, 0, 0))
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 - Qt-Name
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt-Name
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 - Qt-Name
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802 - Qt-Name
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt-Name
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt-Name
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt-Name
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt-Name
        """Alles in einer Zeile -- so breit, wie die Leiste am liebsten wäre."""
        width = height = 0
        for item in self._visible_items():
            hint = item.sizeHint()
            width += hint.width() + (self.spacing() if width else 0)
            height = max(height, hint.height())
        margins = self.contentsMargins()
        return QSize(width + margins.left() + margins.right(),
                     height + margins.top() + margins.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt-Name
        """So schmal wie das breiteste einzelne Element -- schmaler geht es nicht."""
        size = QSize()
        for item in self._visible_items():
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _visible_items(self) -> list[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        # Erst die Zeilen bilden, dann setzen: Für die rechtsbündige Variante
        # muss die Breite einer Zeile feststehen, bevor ihr erstes Element liegt.
        lines: list[list[QLayoutItem]] = [[]]
        used = 0
        for item in self._visible_items():
            width = item.sizeHint().width()
            if lines[-1] and used + self.spacing() + width > area.width():
                lines.append([])
                used = 0
            used += (self.spacing() if lines[-1] else 0) + width
            lines[-1].append(item)
        y = area.y()
        for line in lines:
            if not line:
                continue
            line_width = sum(item.sizeHint().width() for item in line)
            line_width += self.spacing() * (len(line) - 1)
            x = area.x() + max(0, area.width() - line_width) if self.align_right else area.x()
            line_height = max(item.sizeHint().height() for item in line)
            for item in line:
                hint = item.sizeHint()
                if apply:
                    item.setGeometry(QRect(QPoint(x, y), hint))
                x += hint.width() + self.spacing()
            y += line_height + self.spacing()
        return max(0, y - self.spacing() - rect.y()) + margins.bottom()


__all__ = ["FlowLayout"]
