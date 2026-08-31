"""Central branded window icons for all portal windows and dialogs."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap


@lru_cache(maxsize=1)
def kirschke_window_icon() -> QIcon:
    """Return the square Kirschke signet cropped from the wide header logo."""
    logo_path = Path(__file__).resolve().parent / "assets" / "kirschke_logo.png"
    logo = QPixmap(str(logo_path))
    if logo.isNull():
        return QIcon()

    mark_width = min(logo.width(), round(logo.height() * 1.08))
    mark = logo.copy(0, 0, mark_width, logo.height())
    canvas_size = max(mark.width(), mark.height())
    canvas = QPixmap(canvas_size, canvas_size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(
        (canvas_size - mark.width()) // 2,
        (canvas_size - mark.height()) // 2,
        mark,
    )
    painter.end()
    return QIcon(canvas)


__all__ = ["kirschke_window_icon"]
