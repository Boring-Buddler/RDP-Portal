"""Main window for Kirschke RDP Workstation Portal."""

from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QFrame, QSizePolicy, QMessageBox
)
from PySide6.QtCore import Qt, Signal, QSize, Slot
from PySide6.QtGui import QFont

from portal_app.ui.design import DesignSystem, Colors, Typography, Spacing
from portal_app.ui.widgets import WorkstationTableWidget, WorkstationDetailWidget, SessionLogWidget
from portal_app.models.workstation import Workstation, create_mock_workstations
from portal_app.models.user import MockUser, UserRole
from portal_app.models.session import SessionLog, create_mock_session_logs


class MainWindow(QMainWindow):
    """Main window of the RDP Workstation Portal."""
    
    # Signals
    workstation_selected = Signal(Workstation)
    refresh_requested = Signal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        """Initialize the main window."""
        super().__init__(parent)
        
        self.setWindowTitle("Kirschke WORKSTATION CONTROL")
        self.setMinimumSize(QSize(1200, 800))
        
        # State
        self.workstations: list[Workstation] = []
        self.session_logs: list[SessionLog] = []
        self.current_user: MockUser = MockUser.create_user()
        
        # Load mock data
        self._load_mock_data()
        
        # Create UI
        self._create_ui()
        
        # Apply design system
        DesignSystem.apply_to(self)
        
        # Connect signals
        self._connect_signals()
    
    def _load_mock_data(self) -> None:
        """Load mock data for development."""
        self.workstations = create_mock_workstations(20)
        self.session_logs = create_mock_session_logs(10)
    
    def _create_ui(self) -> None:
        """Create the user interface."""
        # Create central widget and layout
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        main_layout.setSpacing(Spacing.MD)
        
        # Create header
        header = self._create_header()
        main_layout.addWidget(header)
        
        # Create navigation bar
        nav_bar = self._create_navigation_bar()
        main_layout.addWidget(nav_bar)
        
        # Create main content area
        content_area = self._create_content_area()
        main_layout.addWidget(content_area, stretch=1)
        
        # Create status bar
        status_bar = self._create_status_bar()
        main_layout.addWidget(status_bar)
    
    def _create_header(self) -> QFrame:
        """Create the header with logo and title."""
        header = QFrame()
        header.setFrameShape(QFrame.NoFrame)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.LG)
        
        # Logo placeholder (Kirschke logo would go here)
        logo_label = QLabel("K")
        logo_label.setStyleSheet(f"""
            QLabel {{
                background-color: {Colors.brand_blue.name()};
                color: {Colors.surface.name()};
                border-radius: {Spacing.SM}px;
                padding: {Spacing.SM}px {Spacing.MD}px;
                font-size: {Typography.FONT_SIZE_2XL}px;
                font-weight: {Typography.FONT_WEIGHT_BOLD};
            }}
        """)
        layout.addWidget(logo_label)
        
        # Title
        title_label = QLabel("WORKSTATION CONTROL")
        title_font = Typography.heading_2()
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"color: {Colors.brand_charcoal.name()};")
        layout.addWidget(title_label, stretch=1)
        
        # User info
        user_label = QLabel(f"Angemeldet als: {self.current_user.display_name}")
        user_label.setStyleSheet(f"color: {Colors.text_muted.name()};")
        layout.addWidget(user_label)
        
        return header
    
    def _create_navigation_bar(self) -> QFrame:
        """Create the navigation bar."""
        nav_bar = QFrame()
        nav_bar.setFrameShape(QFrame.NoFrame)
        nav_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.surface.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                padding: {Spacing.SM}px;
            }}
        """)
        
        layout = QHBoxLayout(nav_bar)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)
        
        # Navigation buttons
        self.overview_btn = QPushButton("Uebersicht")
        self.overview_btn.setCheckable(True)
        self.overview_btn.setChecked(True)
        self.overview_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        
        self.details_btn = QPushButton("Details")
        self.details_btn.setCheckable(True)
        self.details_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        
        self.session_log_btn = QPushButton("Sitzungsprotokoll")
        self.session_log_btn.setCheckable(True)
        self.session_log_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        
        if self.current_user.is_admin:
            self.admin_btn = QPushButton("Administration")
            self.admin_btn.setCheckable(True)
            self.admin_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        
        layout.addWidget(self.overview_btn)
        layout.addWidget(self.details_btn)
        layout.addWidget(self.session_log_btn)
        if self.current_user.is_admin:
            layout.addWidget(self.admin_btn)
        
        # Spacer
        layout.addStretch()
        
        # Action buttons
        self.refresh_btn = QPushButton("Aktualisieren")
        self.refresh_btn.setIconSize(QSize(16, 16))
        self.refresh_btn.setStyleSheet(DesignSystem.styles.button_primary())
        layout.addWidget(self.refresh_btn)
        
        return nav_bar
    
    def _create_content_area(self) -> QFrame:
        """Create the main content area."""
        content_area = QFrame()
        content_area.setFrameShape(QFrame.NoFrame)
        
        layout = QVBoxLayout(content_area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Create stacked widget for different views
        self.stacked_widget = QStackedWidget()
        layout.addWidget(self.stacked_widget)
        
        # Create views
        self._create_views()
        
        return content_area
    
    def _create_views(self) -> None:
        """Create all the different views."""
        # Overview view (default)
        self.overview_view = WorkstationTableWidget(
            self.workstations,
            self.current_user,
            self
        )
        self.overview_view.workstation_selected.connect(self.on_workstation_selected)
        self.overview_view.connect_requested.connect(self.on_connect_requested)
        self.overview_view.flag_requested.connect(self.on_flag_requested)
        self.stacked_widget.addWidget(self.overview_view)
        
        # Detail view
        self.detail_view = WorkstationDetailWidget(self.current_user, self)
        self.stacked_widget.addWidget(self.detail_view)
        
        # Session log view
        self.session_log_view = SessionLogWidget(
            self.session_logs,
            self.current_user,
            self
        )
        self.stacked_widget.addWidget(self.session_log_view)
        
        # Show default view
        self.stacked_widget.setCurrentIndex(0)
    
    def _create_status_bar(self) -> QFrame:
        """Create the status bar."""
        status_bar = QFrame()
        status_bar.setFrameShape(QFrame.NoFrame)
        status_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.surface_alt.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                padding: {Spacing.SM}px {Spacing.MD}px;
            }}
        """)
        
        layout = QHBoxLayout(status_bar)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.LG)
        
        # Status label
        self.status_label = QLabel("Bereit")
        self.status_label.setStyleSheet(f"color: {Colors.text_muted.name()};")
        layout.addWidget(self.status_label, stretch=1)
        
        # Workstation count
        ws_count = len([ws for ws in self.workstations if ws.enabled])
        self.ws_count_label = QLabel(f"{ws_count} Workstations")
        self.ws_count_label.setStyleSheet(f"color: {Colors.text.name()};")
        layout.addWidget(self.ws_count_label)
        
        # Online count
        online_count = len([ws for ws in self.workstations if ws.agent_status.value == "online"])
        self.online_label = QLabel(f"{online_count} Online")
        self.online_label.setStyleSheet(f"color: {Colors.success.name()};")
        layout.addWidget(self.online_label)
        
        return status_bar
    
    def _connect_signals(self) -> None:
        """Connect signals and slots."""
        # Navigation buttons
        self.overview_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.details_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        self.session_log_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        if self.current_user.is_admin:
            self.admin_btn.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(3))
        
        # Refresh button
        self.refresh_btn.clicked.connect(self.on_refresh)
        
        # Workstation selection
        self.workstation_selected.connect(self.detail_view.set_workstation)
        self.workstation_selected.connect(self._update_navigation)
    
    def _update_navigation(self, workstation: Workstation) -> None:
        """Update navigation state when a workstation is selected."""
        self.details_btn.setEnabled(True)
    
    @Slot(Workstation)
    def on_workstation_selected(self, workstation: Workstation) -> None:
        """Handle workstation selection."""
        self.stacked_widget.setCurrentIndex(1)
    
    @Slot(Workstation)
    def on_connect_requested(self, workstation: Workstation) -> None:
        """Handle connect request."""
        if not workstation.can_connect():
            if workstation.is_blocked():
                QMessageBox.warning(
                    self,
                    "Verbindung nicht moeglich",
                    f"Diese Workstation ist gesperrt: {workstation.get_status_display()}"
                )
            else:
                QMessageBox.warning(
                    self,
                    "Verbindung nicht moeglich",
                    "Diese Workstation ist deaktiviert."
                )
            return
        
        # Launch RDP connection
        self._launch_rdp_connection(workstation)
    
    @Slot(Workstation, str)
    def on_flag_requested(self, workstation: Workstation, flag_type: str) -> None:
        """Handle flag set/clear request."""
        # This will be handled by the detail view or a dialog
        pass
    
    def _launch_rdp_connection(self, workstation: Workstation) -> None:
        """Launch RDP connection for a workstation."""
        try:
            from portal_app.rdp import launch_rdp_session
            
            profile = workstation.get_rdp_profile()
            success, message = launch_rdp_session(profile)
            
            if success:
                self.status_label.setText(message)
                # Record launch event
                from portal_app.models.session import SessionEvent, EventType, EventSource
                from datetime import datetime
                
                event = SessionEvent(
                    event_id=f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                    timestamp_utc=datetime.now(),
                    event_type=EventType.LAUNCH_REQUESTED,
                    workstation_id=workstation.workstation_id,
                    workstation_hostname=workstation.hostname,
                    session_user_upn=self.current_user.upn,
                    actor_upn=self.current_user.upn,
                    actor_entra_object_id=self.current_user.object_id,
                    source=EventSource.PORTAL,
                )
                # In a real app, this would be sent to SharePoint
                
                QMessageBox.information(
                    self,
                    "Verbindung gestartet",
                    f"RDP-Verbindung zu {workstation.display_name} wird gestartet."
                )
            else:
                QMessageBox.critical(
                    self,
                    "Fehler",
                    f"RDP-Verbindung konnte nicht gestartet werden: {message}"
                )
        except Exception as e:
            logger.error(f"Failed to launch RDP: {e}")
            QMessageBox.critical(
                self,
                "Fehler",
                f"Fehler beim Starten der RDP-Verbindung: {e}"
            )
    
    def on_refresh(self) -> None:
        """Handle refresh request."""
        self.status_label.setText("Aktualisiere Daten...")
        
        # Reload mock data (in real app, sync with SharePoint)
        self.workstations = create_mock_workstations(20)
        self.overview_view.set_workstations(self.workstations)
        
        self.status_label.setText("Daten aktualisiert")
    
    def closeEvent(self, event) -> None:
        """Handle close event."""
        # Clean up temporary files
        from portal_app.rdp import cleanup_rdp_files
        cleanup_rdp_files()
        
        event.accept()


import logging
logger = logging.getLogger(__name__)
