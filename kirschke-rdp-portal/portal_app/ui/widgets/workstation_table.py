"""Workstation table widget for Kirschke RDP Workstation Portal."""

from typing import Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QComboBox, QLineEdit, QFrame, QLabel,
    QMessageBox, QMenu
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QSortFilterProxyModel
from PySide6.QtGui import QColor, QFont

from portal_app.ui.design import DesignSystem, Colors, Typography, Spacing
from portal_app.models.workstation import Workstation
from portal_app.models.user import User, MockUser
from portal_app.models.session import SessionEvent
from shared.enums import AgentStatus, ManualFlagType


class WorkstationTableWidget(QWidget):
    """Table widget displaying workstations with filtering and sorting."""
    
    # Signals
    workstation_selected = Signal(Workstation)
    connect_requested = Signal(Workstation)
    flag_requested = Signal(Workstation, str)
    
    def __init__(
        self,
        workstations: list[Workstation],
        user: User,
        parent: Optional[QWidget] = None
    ):
        """Initialize the workstation table."""
        super().__init__(parent)
        
        self.workstations = workstations
        self.user = user
        self.filtered_workstations: list[Workstation] = workstations
        
        # Sorting state
        self.sort_column = 0
        self.sort_order = Qt.AscendingOrder
        
        # Create UI
        self._create_ui()
        
        # Apply design system
        self.setStyleSheet(DesignSystem.styles.table_view())
    
    def _create_ui(self) -> None:
        """Create the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)
        
        # Create filter bar
        filter_bar = self._create_filter_bar()
        layout.addWidget(filter_bar)
        
        # Create table
        self.table = self._create_table()
        layout.addWidget(self.table, stretch=1)
        
        # Populate table
        self._populate_table()
    
    def _create_filter_bar(self) -> QFrame:
        """Create the filter bar with controls."""
        filter_bar = QFrame()
        filter_bar.setFrameShape(QFrame.NoFrame)
        filter_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.surface_alt.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                padding: {Spacing.SM}px {Spacing.MD}px;
            }}
        """)
        
        layout = QHBoxLayout(filter_bar)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)
        
        # Search field
        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("Suche nach Name, Standort, Beschreibung...")
        self.search_field.setStyleSheet(DesignSystem.styles.input_field())
        self.search_field.textChanged.connect(self._apply_filters)
        layout.addWidget(self.search_field, stretch=1)
        
        # Site filter
        self.site_filter = QComboBox()
        self.site_filter.addItem("Alle Standorte", "")
        self.site_filter.setStyleSheet(DesignSystem.styles.input_field())
        self.site_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.site_filter)
        
        # Status filter
        self.status_filter = QComboBox()
        self.status_filter.addItem("Alle Status", "")
        self.status_filter.addItem("Bereit", "ready")
        self.status_filter.addItem("Verbunden", "connected")
        self.status_filter.addItem("Getrennt", "disconnected")
        self.status_filter.addItem("Berechnung laeuft", "calculation_running")
        self.status_filter.addItem("Wartung", "maintenance")
        self.status_filter.addItem("Gesperrt", "blocked")
        self.status_filter.setStyleSheet(DesignSystem.styles.input_field())
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.status_filter)
        
        # Agent status filter
        self.agent_filter = QComboBox()
        self.agent_filter.addItem("Alle Agenten", "")
        self.agent_filter.addItem("Online", "online")
        self.agent_filter.addItem("Offline", "offline")
        self.agent_filter.addItem("Veraltet", "stale")
        self.agent_filter.addItem("Fehler", "error")
        self.agent_filter.setStyleSheet(DesignSystem.styles.input_field())
        self.agent_filter.currentIndexChanged.connect(self._apply_filters)
        layout.addWidget(self.agent_filter)
        
        # Populate site filter with actual sites
        self._populate_site_filter()
        
        return filter_bar
    
    def _populate_site_filter(self) -> None:
        """Populate site filter with unique sites from workstations."""
        sites = set(ws.site for ws in self.workstations if ws.site)
        for site in sorted(sites):
            self.site_filter.addItem(site, site)
    
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
            "ID",
            "Name",
            "Standort",
            "Status",
            "Agent",
            "Sitzung",
            "Benutzer",
            "Aktionen",
        ]
        table.setHorizontalHeaderLabels(headers)
        
        # Configure header
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSortIndicatorShown(True)
        header.sortIndicatorChanged.connect(self._on_sort_changed)
        
        # Configure columns
        table.setColumnWidth(0, 80)  # ID
        table.setColumnWidth(1, 200)  # Name
        table.setColumnWidth(2, 120)  # Standort
        table.setColumnWidth(3, 120)  # Status
        table.setColumnWidth(4, 100)  # Agent
        table.setColumnWidth(5, 120)  # Sitzung
        table.setColumnWidth(6, 150)  # Benutzer
        table.setColumnWidth(7, 100)  # Aktionen
        
        # Connect double-click
        table.doubleClicked.connect(self._on_row_double_clicked)
        
        # Connect selection
        table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        
        # Context menu
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        
        return table
    
    def _populate_table(self) -> None:
        """Populate the table with workstation data."""
        self._apply_filters()
    
    def _apply_filters(self) -> None:
        """Apply all filters and refresh the table."""
        # Get filter values
        search_text = self.search_field.text().lower()
        site_filter = self.site_filter.currentData()
        status_filter = self.status_filter.currentData()
        agent_filter = self.agent_filter.currentData()
        
        # Filter workstations
        self.filtered_workstations = []
        for ws in self.workstations:
            if not ws.enabled:
                continue
            
            # Search filter
            if search_text:
                search_match = (
                    search_text in ws.workstation_id.lower() or
                    search_text in ws.display_name.lower() or
                    (ws.site and search_text in ws.site.lower()) or
                    (ws.description and search_text in ws.description.lower()) or
                    (ws.hostname and search_text in ws.hostname.lower())
                )
                if not search_match:
                    continue
            
            # Site filter
            if site_filter and ws.site != site_filter:
                continue
            
            # Status filter
            if status_filter:
                status_match = False
                if status_filter == "ready":
                    status_match = (
                        not ws.is_blocked() and 
                        ws.current_session_state.value == "none"
                    )
                elif status_filter == "connected":
                    status_match = ws.current_session_state.value == "connected"
                elif status_filter == "disconnected":
                    status_match = ws.current_session_state.value == "disconnected"
                elif status_filter == "calculation_running":
                    status_match = ws.manual_flag_type.value == "calculation_running"
                elif status_filter == "maintenance":
                    status_match = ws.manual_flag_type.value == "maintenance"
                elif status_filter == "blocked":
                    status_match = ws.manual_flag_type.value == "blocked"
                
                if not status_match:
                    continue
            
            # Agent filter
            if agent_filter and ws.agent_status.value != agent_filter:
                continue
            
            self.filtered_workstations.append(ws)
        
        # Refresh table
        self._refresh_table()
        
        # Update status label
        self._update_status_label()
    
    def _refresh_table(self) -> None:
        """Refresh the table with filtered workstations."""
        table = self.table
        
        # Clear existing rows
        table.setRowCount(0)
        
        # Sort workstations
        sorted_ws = self._sort_workstations(self.filtered_workstations)
        
        # Add rows
        table.setRowCount(len(sorted_ws))
        
        for row, ws in enumerate(sorted_ws):
            # ID
            table.setItem(row, 0, self._create_cell(ws.workstation_id))
            
            # Name
            table.setItem(row, 1, self._create_cell(ws.display_name))
            
            # Standort
            table.setItem(row, 2, self._create_cell(ws.site or "-"))
            
            # Status
            status_cell = QTableWidgetItem(ws.get_status_display())
            status_cell.setTextAlignment(Qt.AlignCenter)
            
            # Color based on status
            if ws.is_blocked():
                if ws.manual_flag_type == ManualFlagType.BLOCKED:
                    status_cell.setTextColor(QColor(Colors.error.name()))
                elif ws.manual_flag_type == ManualFlagType.MAINTENANCE:
                    status_cell.setTextColor(QColor(Colors.warning.name()))
                else:
                    status_cell.setTextColor(QColor(Colors.info.name()))
            else:
                if ws.current_session_state.value == "connected":
                    status_cell.setTextColor(QColor(Colors.success.name()))
                elif ws.current_session_state.value == "disconnected":
                    status_cell.setTextColor(QColor(Colors.warning.name()))
                else:
                    status_cell.setTextColor(QColor(Colors.text.name()))
            
            table.setItem(row, 3, status_cell)
            
            # Agent
            agent_cell = QTableWidgetItem(ws.get_agent_status_display())
            agent_cell.setTextAlignment(Qt.AlignCenter)
            if ws.agent_status == AgentStatus.ONLINE:
                agent_cell.setTextColor(QColor(Colors.success.name()))
            elif ws.agent_status == AgentStatus.STALE:
                agent_cell.setTextColor(QColor(Colors.warning.name()))
            elif ws.agent_status == AgentStatus.OFFLINE:
                agent_cell.setTextColor(QColor(Colors.text_muted.name()))
            else:
                agent_cell.setTextColor(QColor(Colors.error.name()))
            table.setItem(row, 4, agent_cell)
            
            # Sitzung
            session_cell = QTableWidgetItem(self._get_session_display(ws))
            session_cell.setTextAlignment(Qt.AlignCenter)
            table.setItem(row, 5, session_cell)
            
            # Benutzer
            user_cell = QTableWidgetItem(ws.get_session_user_display())
            table.setItem(row, 6, user_cell)
            
            # Aktionen - Connect button
            connect_btn = ConnectButton(ws, self.user)
            connect_btn.setStyleSheet(DesignSystem.styles.button_primary())
            connect_btn.connect_requested.connect(self.connect_requested)
            table.setCellWidget(row, 7, connect_btn)
        
        # Resize columns to contents
        table.resizeColumnsToContents()
    
    def _get_session_display(self, ws: Workstation) -> str:
        """Get session display text."""
        if ws.current_session_state.value == "none":
            return "-"
        return ws.current_session_state.value.replace("_", " ")
    
    def _create_cell(self, text: str) -> QTableWidgetItem:
        """Create a table cell with text."""
        cell = QTableWidgetItem(text)
        cell.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        return cell
    
    def _sort_workstations(
        self, 
        workstations: list[Workstation]
    ) -> list[Workstation]:
        """Sort workstations based on current sort settings."""
        if not workstations:
            return workstations
        
        reverse = self.sort_order == Qt.DescendingOrder
        
        sort_keys = {
            0: lambda ws: ws.workstation_id,
            1: lambda ws: ws.display_name,
            2: lambda ws: ws.site or "",
            3: lambda ws: ws.get_status_display(),
            4: lambda ws: ws.get_agent_status_display(),
            5: lambda ws: ws.current_session_state.value,
            6: lambda ws: ws.get_session_user_display(),
            7: lambda ws: "",  # No sorting for actions column
        }
        
        sort_key = sort_keys.get(self.sort_column, lambda ws: "")
        return sorted(workstations, key=sort_key, reverse=reverse)
    
    def _on_sort_changed(self, index: int, order: Qt.SortOrder) -> None:
        """Handle sort indicator changed."""
        self.sort_column = index
        self.sort_order = order
        self._refresh_table()
    
    def _on_selection_changed(self) -> None:
        """Handle selection changed."""
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            if row < len(self.filtered_workstations):
                ws = self.filtered_workstations[row]
                self.workstation_selected.emit(ws)
    
    def _on_row_double_clicked(self, index) -> None:
        """Handle row double-clicked."""
        row = index.row()
        if row < len(self.filtered_workstations):
            ws = self.filtered_workstations[row]
            self.workstation_selected.emit(ws)
    
    def _show_context_menu(self, pos) -> None:
        """Show context menu for table."""
        # Get selected workstation
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return
        
        row = selected_rows[0].row()
        if row >= len(self.filtered_workstations):
            return
        
        ws = self.filtered_workstations[row]
        
        # Create menu
        menu = QMenu(self)
        
        # Connect action
        connect_action = menu.addAction("Verbinden")
        connect_action.setEnabled(ws.can_connect())
        connect_action.triggered.connect(lambda: self.connect_requested.emit(ws))
        
        menu.addSeparator()
        
        # Flag actions
        if self.user.is_admin or ws.can_set_flag(ManualFlagType.CALCULATION_RUNNING):
            flag_menu = menu.addMenu("Flag setzen")
            
            calc_action = flag_menu.addAction("Berechnung laeuft")
            calc_action.triggered.connect(
                lambda: self.flag_requested.emit(ws, "calculation_running")
            )
            
            if self.user.is_admin:
                maint_action = flag_menu.addAction("Wartung")
                maint_action.triggered.connect(
                    lambda: self.flag_requested.emit(ws, "maintenance")
                )
                
                blocked_action = flag_menu.addAction("Gesperrt")
                blocked_action.triggered.connect(
                    lambda: self.flag_requested.emit(ws, "blocked")
                )
        
        # Clear flag action
        if ws.is_blocked() and (self.user.is_admin or ws.can_clear_flag(self.user.is_admin)):
            clear_action = menu.addAction("Flag entfernen")
            clear_action.triggered.connect(
                lambda: self.flag_requested.emit(ws, "clear")
            )
        
        # Admin actions
        if self.user.is_admin:
            menu.addSeparator()
            
            # Disconnect
            disconnect_action = menu.addAction("Sitzung trennen")
            disconnect_action.setEnabled(ws.current_session_state.value != "none")
            disconnect_action.triggered.connect(
                lambda: self._admin_disconnect(ws)
            )
            
            # Logoff
            logoff_action = menu.addAction("Sitzung abmelden")
            logoff_action.setEnabled(ws.current_session_state.value != "none")
            logoff_action.triggered.connect(
                lambda: self._admin_logoff(ws)
            )
        
        # Show menu
        menu.exec(self.table.viewport().mapToGlobal(pos))
    
    def _admin_disconnect(self, ws: Workstation) -> None:
        """Handle admin disconnect request."""
        reply = QMessageBox.question(
            self,
            "Sitzung trennen",
            f"Moechten Sie die Sitzung auf {ws.display_name} wirklich trennen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # In a real app, this would send a command to the agent
            QMessageBox.information(
                self,
                "Befehl gesendet",
                f"Trennungsbefehl an {ws.display_name} gesendet."
            )
    
    def _admin_logoff(self, ws: Workstation) -> None:
        """Handle admin logoff request with warning."""
        reply = QMessageBox.question(
            self,
            "Sitzung abmelden",
            f"WARNUNG: Dies wird alle laufenden Programme auf {ws.display_name} beenden.\n"
            f"Moechten Sie wirklich abmelden?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # In a real app, this would send a command to the agent
            # with override if there's a flag
            QMessageBox.information(
                self,
                "Befehl gesendet",
                f"Abmeldebefehl an {ws.display_name} gesendet."
            )
    
    def _update_status_label(self) -> None:
        """Update the status label with filter results."""
        count = len(self.filtered_workstations)
        total = len([ws for ws in self.workstations if ws.enabled])
        
        # Find parent main window and update its status
        parent = self.parent()
        while parent and not hasattr(parent, 'ws_count_label'):
            parent = parent.parent()
        
        if parent and hasattr(parent, 'ws_count_label'):
            parent.ws_count_label.setText(f"{count} von {total} Workstations")
    
    def set_workstations(self, workstations: list[Workstation]) -> None:
        """Set the list of workstations and refresh the table."""
        self.workstations = workstations
        self._populate_site_filter()
        self._apply_filters()
    
    def refresh(self) -> None:
        """Refresh the table data."""
        self._apply_filters()
