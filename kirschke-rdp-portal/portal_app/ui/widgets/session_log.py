"""Session log widget for Kirschke RDP Workstation Portal."""

import csv
import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from portal_app.models.session import SessionEvent, SessionLog
from portal_app.models.user import User
from portal_app.ui.design import Spacing, Typography
from shared.enums import EventResult, EventType


class SessionLogWidget(QWidget):
    """Widget for displaying and filtering session logs."""

    # Signals
    session_selected = Signal(SessionLog)
    export_requested = Signal()

    def __init__(
        self,
        session_logs: list[SessionLog],
        user: User,
        parent: QWidget | None = None
    ):
        """Initialize the session log widget."""
        super().__init__(parent)

        self.session_logs = session_logs
        self.all_events: list[SessionEvent] = []
        self.filtered_events: list[SessionEvent] = []
        self.user = user

        # Load all events from logs
        for log in session_logs:
            self.all_events.extend(log.events)

        # Create UI
        self._create_ui()

        self.setObjectName("sessionLog")

    def _create_ui(self) -> None:
        """Create the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)

        # Create header
        header = self._create_header()
        layout.addWidget(header)

        # Create filter bar
        filter_bar = self._create_filter_bar()
        layout.addWidget(filter_bar)

        # Create table
        self.table = self._create_table()
        layout.addWidget(self.table, stretch=1)

        # Populate table
        self._populate_table()

    def _create_header(self) -> QFrame:
        """Create the header."""
        header = QFrame()
        header.setFrameShape(QFrame.NoFrame)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        # Title
        title_label = QLabel("Sitzungsprotokoll")
        title_label.setObjectName("logTitle")
        title_font = Typography.heading_2()
        title_label.setFont(title_font)
        layout.addWidget(title_label, stretch=1)

        # Export button
        export_btn = QPushButton("Exportieren")
        export_btn.setObjectName("toolbarButton")
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)

        return header

    def _create_filter_bar(self) -> QFrame:
        """Create the filter bar."""
        filter_bar = QFrame()
        filter_bar.setObjectName("filterBar")
        filter_bar.setFrameShape(QFrame.NoFrame)

        layout = QHBoxLayout(filter_bar)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)

        # Workstation filter
        self.ws_filter = QComboBox()
        self.ws_filter.addItem("Alle Workstations", "")
        self._populate_workstation_filter()
        self.ws_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.ws_filter)

        # User filter
        self.user_filter = QComboBox()
        self.user_filter.addItem("Alle Benutzer", "")
        self._populate_user_filter()
        self.user_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.user_filter)

        # Event type filter
        self.type_filter = QComboBox()
        self.type_filter.addItem("Alle Ereignistypen", "")
        self._populate_type_filter()
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.type_filter)

        # Date range filter
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.date_from.dateChanged.connect(self._apply_filters)
        layout.addWidget(self.date_from)

        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.dateChanged.connect(self._apply_filters)
        layout.addWidget(self.date_to)

        return filter_bar

    def _populate_workstation_filter(self) -> None:
        """Populate workstation filter with unique workstation IDs."""
        workstation_ids = {event.workstation_id for event in self.all_events}
        for ws_id in sorted(workstation_ids):
            self.ws_filter.addItem(ws_id, ws_id)

    def _populate_user_filter(self) -> None:
        """Populate user filter with unique user UPNs."""
        users = set()
        for event in self.all_events:
            if event.session_user_upn:
                users.add(event.session_user_upn)
            if event.actor_upn:
                users.add(event.actor_upn)

        for user in sorted(users):
            self.user_filter.addItem(user, user)

    def _populate_type_filter(self) -> None:
        """Populate event type filter."""
        type_names = {
            EventType.LAUNCH_REQUESTED: "Verbindung gestartet",
            EventType.RDP_LOGON: "RDP-Anmeldung",
            EventType.RDP_RECONNECT: "Wiederverbindung",
            EventType.RDP_DISCONNECT: "Verbindung getrennt",
            EventType.RDP_LOGOFF: "Abmeldung",
            EventType.ADMIN_DISCONNECT_REQUESTED: "Admin: Trennung angefordert",
            EventType.ADMIN_DISCONNECT_COMPLETED: "Admin: Trennung erfolgreich",
            EventType.ADMIN_DISCONNECT_FAILED: "Admin: Trennung fehlgeschlagen",
            EventType.ADMIN_LOGOFF_REQUESTED: "Admin: Abmeldung angefordert",
            EventType.ADMIN_LOGOFF_COMPLETED: "Admin: Abmeldung erfolgreich",
            EventType.ADMIN_LOGOFF_FAILED: "Admin: Abmeldung fehlgeschlagen",
            EventType.MANUAL_FLAG_SET: "Flag gesetzt",
            EventType.MANUAL_FLAG_CLEARED: "Flag entfernt",
            EventType.ADMIN_OVERRIDE: "Admin-Override",
        }

        for event_type, name in type_names.items():
            self.type_filter.addItem(name, event_type.value)

    def _create_table(self) -> QTableWidget:
        """Create the table widget."""
        table = QTableWidget()
        table.setColumnCount(8)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.setShowGrid(True)
        table.setGridStyle(Qt.SolidLine)
        table.setAlternatingRowColors(True)

        # Set column headers
        headers = [
            "Zeitpunkt",
            "Ereignistyp",
            "Workstation",
            "Benutzer",
            "Ergebnis",
            "Quelle",
            "Session-ID",
            "Details",
        ]
        table.setHorizontalHeaderLabels(headers)

        # Configure header
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSortIndicatorShown(True)
        header.sortIndicatorChanged.connect(self._on_sort_changed)

        # Configure columns
        table.setColumnWidth(0, 160)  # Timestamp
        table.setColumnWidth(1, 180)  # Event type
        table.setColumnWidth(2, 120)  # Workstation
        table.setColumnWidth(3, 150)  # User
        table.setColumnWidth(4, 100)  # Result
        table.setColumnWidth(5, 100)  # Source
        table.setColumnWidth(6, 80)   # Session ID
        table.setColumnWidth(7, 200)  # Details

        # Connect double-click
        table.doubleClicked.connect(self._on_row_double_clicked)

        return table

    def _populate_table(self) -> None:
        """Populate the table with event data."""
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Apply all filters and refresh the table."""
        # Get filter values
        ws_filter = self.ws_filter.currentData()
        user_filter = self.user_filter.currentData()
        type_filter = self.type_filter.currentData()
        date_from = self.date_from.date().toPython()
        date_to = self.date_to.date().toPython()

        # Convert dates to datetime
        from_date = datetime(date_from.year, date_from.month, date_from.day)
        to_date = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)

        # Filter events
        self.filtered_events = []
        for event in self.all_events:
            # Workstation filter
            if ws_filter and event.workstation_id != ws_filter:
                continue

            # User filter
            if user_filter:
                user_match = (
                    event.session_user_upn == user_filter or
                    event.actor_upn == user_filter
                )
                if not user_match:
                    continue

            # Type filter
            if type_filter and event.event_type.value != type_filter:
                continue

            # Date filter
            if event.timestamp_utc < from_date or event.timestamp_utc > to_date:
                continue

            self.filtered_events.append(event)

        # Refresh table
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Refresh the table with filtered events."""
        table = self.table

        # Clear existing rows
        table.setRowCount(0)

        # Sort events
        sorted_events = sorted(
            self.filtered_events,
            key=lambda e: e.timestamp_utc,
            reverse=True  # Newest first
        )

        # Add rows
        table.setRowCount(len(sorted_events))

        for row, event in enumerate(sorted_events):
            # Timestamp
            timestamp_str = event.timestamp_utc.strftime("%Y-%m-%d %H:%M:%S")
            table.setItem(row, 0, self._create_cell(timestamp_str))

            # Event type
            type_cell = QTableWidgetItem(event.get_display_type())
            table.setItem(row, 1, type_cell)

            # Workstation
            table.setItem(row, 2, self._create_cell(event.workstation_id))

            # User
            user = event.session_user_upn or event.actor_upn or "-"
            table.setItem(row, 3, self._create_cell(user))

            # Result
            result_cell = QTableWidgetItem(event.get_display_result())
            if event.result:
                if event.result == EventResult.SUCCESS:
                    result_cell.setForeground(QColor(Colors.success))
                elif event.result == EventResult.FAILED:
                    result_cell.setForeground(QColor(Colors.error))
                elif event.result == EventResult.WARNING:
                    result_cell.setForeground(QColor(Colors.warning))
            table.setItem(row, 4, result_cell)

            # Source
            source_cell = QTableWidgetItem(event.source.value.replace("_", " "))
            table.setItem(row, 5, source_cell)

            # Session ID
            session_id = str(event.windows_session_id) if event.windows_session_id else "-"
            table.setItem(row, 6, self._create_cell(session_id))

            # Details
            details_parts = []
            if event.client_name:
                details_parts.append(f"Client: {event.client_name}")
            if event.client_ip:
                details_parts.append(f"IP: {event.client_ip}")
            if event.reason:
                details_parts.append(f"Grund: {event.reason}")
            details = ", ".join(details_parts) if details_parts else "-"
            table.setItem(row, 7, self._create_cell(details))

        # Resize columns to contents
        table.resizeColumnsToContents()

    def _create_cell(self, text: str) -> QTableWidgetItem:
        """Create a table cell with text."""
        cell = QTableWidgetItem(text)
        cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return cell

    def _on_sort_changed(self, index: int, order: Qt.SortOrder) -> None:
        """Handle sort indicator changed."""
        self._apply_filters()

    def _on_row_double_clicked(self, index) -> None:
        """Handle row double-clicked."""
        row = index.row()
        if row < len(self.filtered_events):
            event = self.filtered_events[row]
            # Find the session log containing this event
            for log in self.session_logs:
                if event.event_id in [e.event_id for e in log.events]:
                    self.session_selected.emit(log)
                    break

    def _on_export(self) -> None:
        """Handle export request."""
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Sitzungsprotokoll exportieren",
            "sitzungsprotokoll.csv",
            "CSV-Datei (*.csv);;JSON-Datei (*.json)",
        )
        if not path:
            return
        export_path = Path(path)
        if not export_path.suffix:
            export_path = export_path.with_suffix(".json" if "JSON" in selected_filter else ".csv")
        rows = [event_to_export_row(event) for event in self.filtered_events]
        try:
            if export_path.suffix.lower() == ".json":
                export_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                with export_path.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else EXPORT_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)
        except OSError as exc:
            QMessageBox.critical(self, "Export fehlgeschlagen", str(exc))
            return
        QMessageBox.information(self, "Export abgeschlossen", f"{len(rows)} Ereignisse wurden exportiert.")

    def set_session_logs(self, session_logs: list[SessionLog]) -> None:
        """Set the list of session logs and refresh."""
        self.session_logs = session_logs

        # Reload all events
        self.all_events = []
        for log in session_logs:
            self.all_events.extend(log.events)

        # Repopulate filters
        self._populate_workstation_filter()
        self._populate_user_filter()

        # Refresh table
        self._apply_filters()


EXPORT_COLUMNS = [
    "timestamp",
    "event_type",
    "workstation_id",
    "user",
    "result",
    "source",
    "session_id",
    "client_name",
    "client_ip",
    "reason",
]


def event_to_export_row(event: SessionEvent) -> dict[str, str | int | None]:
    return {
        "timestamp": event.timestamp_utc.isoformat(),
        "event_type": event.event_type.value,
        "workstation_id": event.workstation_id,
        "user": event.session_user_upn or event.actor_upn,
        "result": event.result.value if event.result else None,
        "source": event.source.value,
        "session_id": event.windows_session_id,
        "client_name": event.client_name,
        "client_ip": event.client_ip,
        "reason": event.reason,
    }


__all__ = ["SessionLogWidget", "event_to_export_row"]
