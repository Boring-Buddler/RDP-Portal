"""Workstation detail widget for Kirschke RDP Workstation Portal."""

from typing import Optional
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QPushButton, QTextEdit, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont

from portal_app.ui.design import DesignSystem, Colors, Typography, Spacing
from portal_app.models.workstation import Workstation
from portal_app.models.user import User, MockUser
from portal_app.models.session import SessionEvent, EventType, EventSource
from shared.enums import ManualFlagType
from portal_app.ui.widgets.status_badge import StatusBadgeWidget
from portal_app.ui.widgets.flag_dialog import FlagDialog


class WorkstationDetailWidget(QWidget):
    """Widget displaying detailed information about a workstation."""
    
    # Signals
    workstation_updated = Signal(Workstation)
    connect_requested = Signal(Workstation)
    back_requested = Signal()
    
    def __init__(self, user: User, parent: Optional[QWidget] = None):
        """Initialize the detail widget."""
        super().__init__(parent)
        
        self.user = user
        self.workstation: Optional[Workstation] = None
        
        # Create UI
        self._create_ui()
    
    def _create_ui(self) -> None:
        """Create the user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        layout.setSpacing(Spacing.MD)
        
        # Header with navigation
        header = self._create_header()
        layout.addWidget(header)
        
        # Main content
        content = self._create_content()
        layout.addWidget(content, stretch=1)
    
    def _create_header(self) -> QFrame:
        """Create the header with title and navigation."""
        header = QFrame()
        header.setFrameShape(QFrame.NoFrame)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)
        
        # Back button
        self.back_btn = QPushButton("< Zurueck")
        self.back_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        self.back_btn.clicked.connect(self._on_back)
        layout.addWidget(self.back_btn)
        
        # Title
        self.title_label = QLabel("Workstation-Details")
        title_font = Typography.heading_2()
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet(f"color: {Colors.brand_charcoal.name()};")
        layout.addWidget(self.title_label, stretch=1)
        
        # Status
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        
        return header
    
    def _create_content(self) -> QWidget:
        """Create the main content area."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.MD)
        
        # Profile group
        profile_group = self._create_profile_group()
        layout.addWidget(profile_group)
        
        # Status group
        status_group = self._create_status_group()
        layout.addWidget(status_group)
        
        # Session group
        session_group = self._create_session_group()
        layout.addWidget(session_group)
        
        # RDP Profile group
        rdp_group = self._create_rdp_group()
        layout.addWidget(rdp_group)
        
        # Action buttons
        actions = self._create_actions()
        layout.addWidget(actions)
        
        return content
    
    def _create_profile_group(self) -> QGroupBox:
        """Create the profile information group."""
        group = QGroupBox("Stammdaten")
        group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                margin-top: {Spacing.SM}px;
                padding-top: {Spacing.MD}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {Spacing.MD}px;
                padding: 0 {Spacing.SM}px;
            }}
        """)
        
        layout = QFormLayout(group)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.SM)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        layout.setFormAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # Workstation ID
        self.ws_id_label = QLabel()
        self.ws_id_label.setStyleSheet(f"font-family: {Typography.FONT_FAMILY};")
        layout.addRow("Workstation-ID:", self.ws_id_label)
        
        # Display Name
        self.display_name_label = QLabel()
        self.display_name_label.setStyleSheet(f"font-weight: {Typography.FONT_WEIGHT_SEMIBOLD};")
        layout.addRow("Anzeigename:", self.display_name_label)
        
        # Hostname
        self.hostname_label = QLabel()
        layout.addRow("Hostname:", self.hostname_label)
        
        # FQDN
        self.fqdn_label = QLabel()
        layout.addRow("FQDN:", self.fqdn_label)
        
        # Site
        self.site_label = QLabel()
        layout.addRow("Standort:", self.site_label)
        
        # Description
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        layout.addRow("Beschreibung:", self.description_label)
        
        return group
    
    def _create_status_group(self) -> QGroupBox:
        """Create the status information group."""
        group = QGroupBox("Status")
        group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                margin-top: {Spacing.SM}px;
                padding-top: {Spacing.MD}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {Spacing.MD}px;
                padding: 0 {Spacing.SM}px;
            }}
        """)
        
        layout = QHBoxLayout(group)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.LG)
        
        # Status column
        status_layout = QVBoxLayout()
        status_layout.setSpacing(Spacing.MD)
        
        # Overall status
        status_title = QLabel("Gesamtstatus:")
        status_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        status_layout.addWidget(status_title)
        
        self.overall_status_badge = StatusBadgeWidget("-")
        status_layout.addWidget(self.overall_status_badge)
        
        # Agent status
        agent_title = QLabel("Agent-Status:")
        agent_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        status_layout.addWidget(agent_title)
        
        self.agent_status_badge = StatusBadgeWidget("-")
        status_layout.addWidget(self.agent_status_badge)
        
        layout.addLayout(status_layout)
        
        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet(f"color: {Colors.border.name()};")
        layout.addWidget(sep)
        
        # Session column
        session_layout = QVBoxLayout()
        session_layout.setSpacing(Spacing.MD)
        
        # Session state
        session_title = QLabel("Sitzungsstatus:")
        session_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        session_layout.addWidget(session_title)
        
        self.session_status_badge = StatusBadgeWidget("-")
        session_layout.addWidget(self.session_status_badge)
        
        # Current user
        user_title = QLabel("Aktueller Benutzer:")
        user_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        session_layout.addWidget(user_title)
        
        self.current_user_label = QLabel("-")
        self.current_user_label.setStyleSheet(f"font-weight: {Typography.FONT_WEIGHT_SEMIBOLD};")
        session_layout.addWidget(self.current_user_label)
        
        layout.addLayout(session_layout)
        
        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setFrameShadow(QFrame.Sunken)
        sep2.setStyleSheet(f"color: {Colors.border.name()};")
        layout.addWidget(sep2)
        
        # Manual flag column
        flag_layout = QVBoxLayout()
        flag_layout.setSpacing(Spacing.MD)
        
        # Manual flag
        flag_title = QLabel("Manuelles Flag:")
        flag_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        flag_layout.addWidget(flag_title)
        
        self.flag_badge = StatusBadgeWidget("-")
        flag_layout.addWidget(self.flag_badge)
        
        # Flag reason
        reason_title = QLabel("Grund:")
        reason_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        flag_layout.addWidget(reason_title)
        
        self.flag_reason_label = QLabel("-")
        self.flag_reason_label.setWordWrap(True)
        flag_layout.addWidget(self.flag_reason_label)
        
        layout.addLayout(flag_layout)
        
        # Last seen
        last_seen_title = QLabel("Agent zuletzt gesehen:")
        last_seen_title.setStyleSheet(f"color: {Colors.text_muted.name()};")
        flag_layout.addWidget(last_seen_title)
        
        self.last_seen_label = QLabel("-")
        self.last_seen_label.setStyleSheet(f"font-size: {Typography.FONT_SIZE_SM}px;")
        flag_layout.addWidget(self.last_seen_label)
        
        layout.addStretch()
        
        return group
    
    def _create_session_group(self) -> QGroupBox:
        """Create the session information group."""
        group = QGroupBox("Letzte Sitzung")
        group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                margin-top: {Spacing.SM}px;
                padding-top: {Spacing.MD}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {Spacing.MD}px;
                padding: 0 {Spacing.SM}px;
            }}
        """)
        
        layout = QFormLayout(group)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.SM)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        # Last session event
        self.last_event_label = QLabel()
        layout.addRow("Letzte Aenderung:", self.last_event_label)
        
        # Session user
        self.session_user_label = QLabel()
        layout.addRow("Sitzungsbenutzer:", self.session_user_label)
        
        # Session duration
        self.session_duration_label = QLabel()
        layout.addRow("Sitzungsdauer:", self.session_duration_label)
        
        return group
    
    def _create_rdp_group(self) -> QGroupBox:
        """Create the RDP profile group."""
        group = QGroupBox("RDP-Profil")
        group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                margin-top: {Spacing.SM}px;
                padding-top: {Spacing.MD}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {Spacing.MD}px;
                padding: 0 {Spacing.SM}px;
            }}
        """)
        
        layout = QFormLayout(group)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.SM)
        layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        
        # Username hint
        self.username_hint_label = QLabel()
        layout.addRow("Benutzername-Hinweis:", self.username_hint_label)
        
        # Entra SSO
        self.entra_sso_label = QLabel()
        layout.addRow("Entra-SSO aktiviert:", self.entra_sso_label)
        
        # Gateway
        self.gateway_label = QLabel()
        layout.addRow("Gateway:", self.gateway_label)
        
        # Multi-monitor
        self.multimon_label = QLabel()
        layout.addRow("Mehrmonitore:", self.multimon_label)
        
        # Redirection
        self.redirect_label = QLabel()
        layout.addRow("Umleitungen:", self.redirect_label)
        
        return group
    
    def _create_actions(self) -> QFrame:
        """Create the action buttons area."""
        actions = QFrame()
        actions.setFrameShape(QFrame.NoFrame)
        actions.setStyleSheet(f"""
            QFrame {{
                background-color: {Colors.surface_alt.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: {Spacing.MD}px;
                padding: {Spacing.MD}px;
            }}
        """)
        
        layout = QHBoxLayout(actions)
        layout.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        layout.setSpacing(Spacing.MD)
        
        # Connect button
        self.connect_btn = QPushButton("Verbinden")
        self.connect_btn.setStyleSheet(DesignSystem.styles.button_primary())
        self.connect_btn.clicked.connect(self._on_connect)
        layout.addWidget(self.connect_btn)
        
        # Set flag button
        self.set_flag_btn = QPushButton("Flag setzen")
        self.set_flag_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        self.set_flag_btn.clicked.connect(self._on_set_flag)
        layout.addWidget(self.set_flag_btn)
        
        # Clear flag button
        self.clear_flag_btn = QPushButton("Flag entfernen")
        self.clear_flag_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        self.clear_flag_btn.clicked.connect(self._on_clear_flag)
        layout.addWidget(self.clear_flag_btn)
        
        # Disconnect button (admin only)
        self.disconnect_btn = QPushButton("Sitzung trennen")
        self.disconnect_btn.setStyleSheet(DesignSystem.styles.button_secondary())
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        layout.addWidget(self.disconnect_btn)
        
        # Logoff button (admin only)
        self.logoff_btn = QPushButton("Sitzung abmelden")
        self.logoff_btn.setStyleSheet(DesignSystem.styles.button_danger())
        self.logoff_btn.clicked.connect(self._on_logoff)
        layout.addWidget(self.logoff_btn)
        
        # Spacer
        layout.addStretch()
        
        return actions
    
    def set_workstation(self, workstation: Workstation) -> None:
        """Set the workstation to display."""
        self.workstation = workstation
        self._update_ui()
    
    def _update_ui(self) -> None:
        """Update all UI elements with workstation data."""
        if not self.workstation:
            return
        
        ws = self.workstation
        
        # Update header
        self.title_label.setText(f"{ws.display_name} ({ws.hostname})")
        self.status_label.setText(ws.get_status_display())
        
        # Update profile
        self.ws_id_label.setText(ws.workstation_id)
        self.display_name_label.setText(ws.display_name)
        self.hostname_label.setText(ws.hostname or "-")
        self.fqdn_label.setText(ws.fqdn or "-")
        self.site_label.setText(ws.site or "-")
        self.description_label.setText(ws.description or "-")
        
        # Update status
        self.overall_status_badge.set_status(
            ws.get_status_display(),
            "error" if ws.is_blocked() else "success" if ws.current_session_state.value == "connected" else "neutral"
        )
        self.agent_status_badge = StatusBadgeWidget.for_agent_status(ws.agent_status)
        self.session_status_badge = StatusBadgeWidget.for_session_state(ws.current_session_state)
        self.flag_badge = StatusBadgeWidget.for_manual_flag(ws.manual_flag_type)
        
        self.current_user_label.setText(ws.get_session_user_display())
        
        # Update last seen
        if ws.agent_last_seen_utc:
            last_seen = ws.agent_last_seen_utc.strftime("%Y-%m-%d %H:%M:%S")
            self.last_seen_label.setText(last_seen)
        else:
            self.last_seen_label.setText("Noch nie")
        
        # Update flag reason
        self.flag_reason_label.setText(ws.manual_flag_reason or "-")
        
        # Update last session
        if ws.last_session_event_utc:
            last_event = ws.last_session_event_utc.strftime("%Y-%m-%d %H:%M:%S")
            self.last_event_label.setText(last_event)
        else:
            self.last_event_label.setText("-")
        
        self.session_user_label.setText(ws.current_session_user or "-")
        self.session_duration_label.setText("-")  # TODO: Calculate from session events
        
        # Update RDP profile
        self.username_hint_label.setText(ws.username_hint or "-")
        self.entra_sso_label.setText("Ja" if ws.entra_sso_enabled else "Nein")
        self.gateway_label.setText(ws.gateway_hostname or "Kein Gateway")
        self.multimon_label.setText("Ja" if ws.use_all_monitors else "Nein")
        
        # Build redirection text
        redirects = []
        if ws.redirect_clipboard:
            redirects.append("Zwischenablage")
        if ws.redirect_drives:
            redirects.append("Laufwerke")
        if ws.redirect_printers:
            redirects.append("Drucker")
        if ws.redirect_audio:
            redirects.append("Audio")
        
        self.redirect_label.setText(", ".join(redirects) if redirects else "Keine")
        
        # Update action buttons
        self._update_action_buttons()
    
    def _update_action_buttons(self) -> None:
        """Update action button states based on workstation and user."""
        if not self.workstation:
            self.connect_btn.setEnabled(False)
            self.set_flag_btn.setEnabled(False)
            self.clear_flag_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(False)
            self.logoff_btn.setEnabled(False)
            return
        
        ws = self.workstation
        
        # Connect button
        self.connect_btn.setEnabled(ws.can_connect())
        
        # Set flag button
        self.set_flag_btn.setEnabled(
            ws.can_set_flag(ManualFlagType.CALCULATION_RUNNING, self.user.is_admin)
        )
        
        # Clear flag button
        self.clear_flag_btn.setEnabled(
            ws.is_blocked() and ws.can_clear_flag(self.user.is_admin)
        )
        
        # Admin buttons
        is_admin = self.user.is_admin
        has_session = ws.current_session_state.value != "none"
        
        self.disconnect_btn.setVisible(is_admin)
        self.disconnect_btn.setEnabled(is_admin and has_session)
        
        self.logoff_btn.setVisible(is_admin)
        self.logoff_btn.setEnabled(is_admin and has_session)
    
    @Slot()
    def _on_back(self) -> None:
        """Handle back button click."""
        self.back_requested.emit()
    
    @Slot()
    def _on_connect(self) -> None:
        """Handle connect button click."""
        if self.workstation:
            self.connect_requested.emit(self.workstation)
    
    @Slot()
    def _on_set_flag(self) -> None:
        """Handle set flag button click."""
        if not self.workstation:
            return
        
        dialog = FlagDialog(self.workstation, self.user, self)
        if dialog.exec() == FlagDialog.Accepted:
            # Flag was set, refresh UI
            self._update_ui()
            if hasattr(self, 'workstation_updated'):
                self.workstation_updated.emit(self.workstation)
    
    @Slot()
    def _on_clear_flag(self) -> None:
        """Handle clear flag button click."""
        if not self.workstation:
            return
        
        reply = QMessageBox.question(
            self,
            "Flag entfernen",
            f"Moechten Sie das Flag '{self.workstation.get_status_display()}' wirklich entfernen?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Clear the flag
            self.workstation.manual_flag_type = ManualFlagType.NONE
            self.workstation.manual_flag_reason = None
            self.workstation.manual_flag_project = None
            self.workstation.manual_flag_set_by_object_id = None
            self.workstation.manual_flag_set_by_upn = None
            self.workstation.manual_flag_set_at_utc = None
            
            # Record event
            event = SessionEvent(
                event_id=f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                timestamp_utc=datetime.now(),
                event_type=EventType.MANUAL_FLAG_CLEARED,
                workstation_id=self.workstation.workstation_id,
                workstation_hostname=self.workstation.hostname,
                actor_upn=self.user.upn,
                actor_entra_object_id=self.user.object_id,
                source=EventSource.PORTAL,
            )
            
            self._update_ui()
            if hasattr(self, 'workstation_updated'):
                self.workstation_updated.emit(self.workstation)
            
            QMessageBox.information(self, "Flag entfernt", "Das Flag wurde erfolgreich entfernt.")
    
    @Slot()
    def _on_disconnect(self) -> None:
        """Handle disconnect button click."""
        if not self.workstation:
            return
        
        reply = QMessageBox.question(
            self,
            "Sitzung trennen",
            f"Moechten Sie die Sitzung auf {self.workstation.display_name} wirklich trennen?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # In a real app, this would send a command to the agent
            # For now, just show a message
            QMessageBox.information(
                self,
                "Befehl gesendet",
                f"Trennungsbefehl an {self.workstation.display_name} gesendet."
            )
    
    @Slot()
    def _on_logoff(self) -> None:
        """Handle logoff button click."""
        if not self.workstation:
            return
        
        if self.workstation.is_blocked():
            reply = QMessageBox.question(
                self,
                "Admin-Override",
                f"Diese Workstation ist gesperrt: {self.workstation.get_status_display()}\n"
                f"Moechten Sie die Sperre mit einer Begruendung ueberschreiben?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Show override dialog
                reason, ok = self._show_override_dialog()
                if ok:
                    # Record override event
                    event = SessionEvent(
                        event_id=f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
                        timestamp_utc=datetime.now(),
                        event_type=EventType.ADMIN_OVERRIDE,
                        workstation_id=self.workstation.workstation_id,
                        workstation_hostname=self.workstation.hostname,
                        actor_upn=self.user.upn,
                        actor_entra_object_id=self.user.object_id,
                        reason=reason,
                        source=EventSource.ADMIN,
                    )
                    
                    # Clear flag temporarily for this operation
                    old_flag = self.workstation.manual_flag_type
                    self.workstation.manual_flag_type = ManualFlagType.NONE
                    
                    # In a real app, this would send logoff command to agent
                    QMessageBox.information(
                        self,
                        "Override durchgefuehrt",
                        f"Sperre ueberschrieben. Logoff-Befehl an {self.workstation.display_name} gesendet."
                    )
                    
                    # Restore flag
                    self.workstation.manual_flag_type = old_flag
                    return
        else:
            reply = QMessageBox.question(
                self,
                "Sitzung abmelden",
                f"WARNUNG: Dies wird alle laufenden Programme auf {self.workstation.display_name} beenden.\n"
                f"Moechten Sie wirklich abmelden?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # In a real app, this would send logoff command to agent
                QMessageBox.information(
                    self,
                    "Befehl gesendet",
                    f"Abmeldebefehl an {self.workstation.display_name} gesendet."
                )
    
    def _show_override_dialog(self) -> tuple[str, bool]:
        """Show override reason dialog."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Override-Begruendung")
        dialog.setMinimumWidth(400)
        
        layout = QVBoxLayout(dialog)
        
        label = QLabel("Bitte geben Sie eine Begruendung fuer den Override ein:")
        layout.addWidget(label)
        
        reason_edit = QTextEdit()
        reason_edit.setStyleSheet(DesignSystem.styles.input_field())
        layout.addWidget(reason_edit)
        
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            return reason_edit.toPlainText().strip(), True
        
        return "", False


__all__ = ["WorkstationDetailWidget"]
