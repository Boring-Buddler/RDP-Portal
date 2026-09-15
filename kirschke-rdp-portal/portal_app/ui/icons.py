"""Central branded window icons for all portal windows and dialogs."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

#: Der Name, unter dem Windows die Fenster dieser Anwendung in der Taskleiste
#: gruppiert.  Ohne eigene ID erbt ein Python-Prozess die des Interpreters --
#: dann zeigt die Taskleiste dessen Symbol statt unseres, und angeheftete
#: Verknuepfungen werden nicht dem laufenden Fenster zugeordnet.
APP_USER_MODEL_ID = "ProfKirschke.RDPPortal"


def set_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Tell Windows which application these windows belong to.

    Best effort: on a system without the shell API -- or when the call is not
    available -- the portal must still start, it just keeps the generic taskbar
    icon.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        return False
    return True


@lru_cache(maxsize=1)
def kirschke_window_icon() -> QIcon:
    """Return the branded application icon for every portal window.

    The ``.ico`` is preferred because it carries every size Windows asks for,
    from the 16 px title bar to the 256 px Explorer tile.  Cropping the signet
    out of the wide logo stays as a fallback for a source tree in which the icon
    has not been generated yet (``deployment/build_app_icon.py``).
    """
    icon_path = Path(__file__).resolve().parent / "assets" / "kirschke.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
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


__all__ = ["APP_USER_MODEL_ID", "kirschke_window_icon", "set_windows_app_id"]
