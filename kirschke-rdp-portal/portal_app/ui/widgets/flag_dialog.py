"""Flag dialog for Kirschke RDP Workstation Portal."""

from typing import Optional
from datetime import datetime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QLineEdit, QTextEdit, QPushButton, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, Signal

from portal_app.ui.design import Typography, Spacing
from portal_app.models.workstation import Workstation
from portal_app.models.user import User
from shared.enums import ManualFlagType
from portal_app.models.session import SessionEvent, EventType, EventSource


class FlagDialog(QDialog):
    """Dialog for setting or clearing manual flags on a workstation."""
    
    def __init__(
        self,
        workstation: Workstation,
        user: User,
        parent: Optional[QDialog] = None
    ):
        """Initialize the flag dialog."""
        super().__init__(parent)
        
        self.workstation = workstation
        self.user = user
        
        self.setWindowTitle(f"Flag setzen: {workstation.display_name}")
        self.setMinimumWidth(400)
        self.setMinimumHeight(300)
        
        # Create UI
        self._create_ui()
        
        self.setObjectName("flagDialog")
    
    def _create_ui(self) -> None:
        """Create the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.MD)
        
        # Title
        title_label = QLabel("Manuelles Flag setzen")
        title_label.setObjectName("dialogTitle")
        title_font = Typography.heading_3()
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Current flag info
        current_flag_label = QLabel(f"Aktuelles Flag: {self.workstation.get_status_display()}")
        current_flag_label.setObjectName("dialogNote")
        layout.addWidget(current_flag_label)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setObjectName("detailDivider")
        layout.addWidget(sep)
        
        # Flag type selection
        flag_layout = QHBoxLayout()
        flag_layout.setSpacing(Spacing.MD)
        
        flag_label = QLabel("Flag-Typ:")
        flag_label.setObjectName("dialogFormLabel")
        flag_layout.addWidget(flag_label)
        
        self.flag_combo = QComboBox()
        
        # Determine which flags the user can set
        if self.user.is_admin:
            self.flag_combo.addItem("Berechnung laeuft", ManualFlagType.CALCULATION_RUNNING)
            self.flag_combo.addItem("Wartung", ManualFlagType.MAINTENANCE)
            self.flag_combo.addItem("Gesperrt", ManualFlagType.BLOCKED)
        else:
            # Regular users can only set calculation_running
            self.flag_combo.addItem("Berechnung laeuft", ManualFlagType.CALCULATION_RUNNING)
        
        flag_layout.addWidget(self.flag_combo, stretch=1)
        
        layout.addLayout(flag_layout)
        
        # Project field
        project_layout = QHBoxLayout()
        project_layout.setSpacing(Spacing.MD)
        
        project_label = QLabel("Projekt/Vorgang (optional):")
        project_label.setObjectName("dialogFormLabel")
        project_layout.addWidget(project_label)
        
        self.project_edit = QLineEdit()
        self.project_edit.setPlaceholderText("z.B. Projekt XYZ-123")
        project_layout.addWidget(self.project_edit, stretch=1)
        
        layout.addLayout(project_layout)
        
        # Reason field
        reason_label = QLabel("Grund (erforderlich):")
        reason_label.setObjectName("dialogFormLabel")
        layout.addWidget(reason_label)
        
        self.reason_edit = QTextEdit()
        self.reason_edit.setPlaceholderText("Bitte geben Sie einen Grund fuer das Flag ein...")
        self.reason_edit.setMinimumHeight(80)
        layout.addWidget(self.reason_edit)
        
        # Warning
        warning_label = QLabel("Hinweis: Dieses Flag blockiert normale Verbindungs- und Abmeldeaktionen.")
        warning_label.setObjectName("dialogWarning")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setObjectName("detailDivider")
        layout.addWidget(sep2)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(Spacing.MD)
        
        # Spacer
        button_layout.addStretch()
        
        # Cancel button
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setObjectName("toolbarButton")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        # Set flag button
        self.set_btn = QPushButton("Flag setzen")
        self.set_btn.setObjectName("cardPrimaryButton")
        self.set_btn.clicked.connect(self._on_set_flag)
        button_layout.addWidget(self.set_btn)
        
        layout.addLayout(button_layout)
        
        # Validate inputs
        self.reason_edit.textChanged.connect(self._validate_inputs)
        self._validate_inputs()
    
    def _validate_inputs(self) -> None:
        """Validate input fields and update button states."""
        reason = self.reason_edit.toPlainText().strip()
        
        # Button is enabled if reason is not empty
        self.set_btn.setEnabled(len(reason) > 0)
    
    def _on_set_flag(self) -> None:
        """Handle set flag button click."""
        # Get selected flag type
        flag_type = self.flag_combo.currentData()
        if not flag_type:
            QMessageBox.warning(self, "Fehler", "Bitte waehlen Sie einen Flag-Typ aus.")
            return
        
        # Get reason
        reason = self.reason_edit.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Fehler", "Bitte geben Sie einen Grund ein.")
            return
        
        # Get project
        project = self.project_edit.text().strip()
        
        # Set the flag on the workstation
        self.workstation.manual_flag_type = flag_type
        self.workstation.manual_flag_reason = reason
        self.workstation.manual_flag_project = project or None
        self.workstation.manual_flag_set_by_object_id = self.user.object_id
        self.workstation.manual_flag_set_by_upn = self.user.upn
        self.workstation.manual_flag_set_at_utc = datetime.now()
        
        # Record event
        event = SessionEvent(
            event_id=f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            timestamp_utc=datetime.now(),
            event_type=EventType.MANUAL_FLAG_SET,
            workstation_id=self.workstation.workstation_id,
            workstation_hostname=self.workstation.hostname,
            actor_upn=self.user.upn,
            actor_entra_object_id=self.user.object_id,
            reason=reason,
            source=EventSource.PORTAL,
        )
        
        # Close dialog
        self.accept()
        
        QMessageBox.information(
            self,
            "Flag gesetzt",
            f"Das Flag '{flag_type.value.replace('_', ' ')}' wurde erfolgreich gesetzt."
        )


__all__ = ["FlagDialog"]
