"""Status badge widget for Kirschke RDP Workstation Portal."""

from typing import Optional
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from portal_app.ui.design import DesignSystem, Colors, Typography, Spacing
from shared.enums import AgentStatus, SessionState, ManualFlagType


class StatusBadgeWidget(QLabel):
    """A badge widget for displaying status with color coding."""
    
    def __init__(
        self,
        text: str,
        status_type: str = "neutral",
        parent: Optional[QFrame] = None
    ):
        """Initialize the status badge.
        
        Args:
            text: The text to display
            status_type: Type of status (determines color)
                        Can be: 'success', 'warning', 'error', 'info', 'neutral'
            parent: Parent widget
        """
        super().__init__(text, parent)
        
        self.status_type = status_type
        self._update_style()
    
    def _update_style(self) -> None:
        """Update the style based on status type."""
        color_map = {
            "success": Colors.success,
            "warning": Colors.warning,
            "error": Colors.error,
            "info": Colors.info,
            "neutral": Colors.text_muted,
        }
        
        bg_color = color_map.get(self.status_type, Colors.text_muted)
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color.name()};
                color: {Colors.surface.name()};
                border-radius: {Spacing.SM}px;
                padding: {Spacing.XXS}px {Spacing.XS}px;
                font-size: {Typography.FONT_SIZE_XS}px;
                font-weight: {Typography.FONT_WEIGHT_SEMIBOLD};
            }}
        """)
        
        self.setAlignment(Qt.AlignCenter)
    
    def set_status(self, text: str, status_type: str) -> None:
        """Update the badge text and status."""
        self.setText(text)
        self.status_type = status_type
        self._update_style()
    
    def set_text(self, text: str) -> None:
        """Update just the text."""
        self.setText(text)
    
    @classmethod
    def for_agent_status(cls, status: AgentStatus, parent: Optional[QFrame] = None) -> "StatusBadgeWidget":
        """Create a badge for agent status."""
        status_map = {
            AgentStatus.ONLINE: ("Online", "success"),
            AgentStatus.STALE: ("Veraltet", "warning"),
            AgentStatus.OFFLINE: ("Offline", "neutral"),
            AgentStatus.ERROR: ("Fehler", "error"),
        }
        text, status_type = status_map.get(status, ("Unbekannt", "neutral"))
        return cls(text, status_type, parent)
    
    @classmethod
    def for_session_state(cls, state: SessionState, parent: Optional[QFrame] = None) -> "StatusBadgeWidget":
        """Create a badge for session state."""
        state_map = {
            SessionState.NONE: ("-", "neutral"),
            SessionState.LOGON: ("Anmeldung", "info"),
            SessionState.CONNECTED: ("Verbunden", "success"),
            SessionState.RECONNECTED: ("Wiederverbunden", "info"),
            SessionState.DISCONNECTED: ("Getrennt", "warning"),
            SessionState.LOGGED_OFF: ("Abgemeldet", "neutral"),
        }
        text, status_type = state_map.get(state, ("Unbekannt", "neutral"))
        return cls(text, status_type, parent)
    
    @classmethod
    def for_manual_flag(cls, flag: ManualFlagType, parent: Optional[QFrame] = None) -> "StatusBadgeWidget":
        """Create a badge for manual flag."""
        flag_map = {
            ManualFlagType.NONE: ("-", "neutral"),
            ManualFlagType.CALCULATION_RUNNING: ("Berechnung laeuft", "info"),
            ManualFlagType.MAINTENANCE: ("Wartung", "warning"),
            ManualFlagType.BLOCKED: ("Gesperrt", "error"),
        }
        text, status_type = flag_map.get(flag, ("Unbekannt", "neutral"))
        return cls(text, status_type, parent)


__all__ = ["StatusBadgeWidget"]
