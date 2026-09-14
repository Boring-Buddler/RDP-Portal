"""Quiet colour key under the machine grid."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from portal_app.ui.machine_actions import legend_entries


class StatusLegend(QLabel):
    """One muted line explaining what the card colours mean.

    Rendered as rich text in a single wrapping label rather than a row of widgets:
    the dashboard narrows to one card per column, and a horizontal layout of seven
    entries would simply be cut off there.  Entries wrap at the gaps between them
    while each dot stays glued to its own label.
    """

    #: Non-breaking space keeps a dot next to its word; the plain spaces around the
    #: separator are where a line may break.
    SEPARATOR = "    "

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Reuses the muted meta style of the cards so the key stays in the
        # background instead of competing with the machines above it.
        self.setObjectName("cardMeta")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setText(self.markup())

    @staticmethod
    def markup() -> str:
        """Build the rich text from the shared state table."""
        return StatusLegend.SEPARATOR.join(
            f'<span style="color:{color.name()};">&#9679;</span>&nbsp;{label}'
            for color, label in legend_entries()
        )


__all__ = ["StatusLegend"]
