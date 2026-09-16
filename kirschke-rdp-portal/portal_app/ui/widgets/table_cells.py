"""Refill a QTableWidget that carries widgets in its cells.

``setRowCount`` and ``clearContents`` drop the *items* of a table, but a widget
placed with ``setCellWidget`` is a child of the viewport and survives both.  On
the second fill it stays where it was drawn, overlapping the new contents -- two
half-visible combo boxes across the first row, which is exactly what the agent
assignment page and the settings table did: the page is re-entered every time
somebody goes back a step, and the settings table is refilled on every status
refresh.

Qt does delete a replaced cell widget, so a table whose cells are *all* refilled
hides the problem until the table gets shorter or a column is left empty.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTableWidget


def reset_rows(table: QTableWidget, rows: int) -> None:
    """Remove every cell widget, then resize the table to ``rows`` rows.

    ``setParent(None)`` is the part that matters and ``deleteLater`` alone is not
    enough: a deferred deletion is only carried out when the event loop next
    runs, and until then the widget is still a visible child of the viewport --
    still drawn over the freshly filled rows. Detaching it first takes it out of
    the viewport at once; deleteLater then frees it safely, which ``del`` would
    not, because the widget may be in the middle of emitting the very signal that
    led here.
    """
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            widget = table.cellWidget(row, column)
            if widget is not None:
                table.removeCellWidget(row, column)
                widget.setParent(None)
                widget.deleteLater()
    table.clearContents()
    table.setRowCount(rows)


__all__ = ["reset_rows"]
