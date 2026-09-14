"""Connect button widget for Kirschke RDP Workstation Portal."""


from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.design import Colors, DesignSystem
from shared.enums import ManualFlagType


class ConnectButton(QPushButton):
    """Custom button for connecting to workstations.

    The button changes appearance based on workstation status
    and emits signals when clicked.
    """

    # Signals
    connect_requested = Signal(Workstation)

    def __init__(self, workstation: Workstation, user: User, parent: QPushButton | None = None):
        """Initialize the connect button."""
        super().__init__(parent)

        self.workstation = workstation
        self.user = user

        # Set button properties
        self.setText("Verbinden")
        self.setFixedSize(130, 30)

        # Update appearance based on status
        self._update_appearance()

        # Connect click
        self.clicked.connect(self._on_clicked)

    def _update_appearance(self) -> None:
        """Update button appearance based on workstation status."""
        if not self.workstation.enabled:
            self.setText("Deaktiviert")
            self.setStyleSheet(self._get_disabled_style())
            self.setEnabled(False)
            return

        if self.workstation.is_blocked():
            if self.workstation.manual_flag_type == ManualFlagType.BLOCKED:
                self.setText("Gesperrt")
                self.setStyleSheet(self._get_blocked_style())
            elif self.workstation.manual_flag_type == ManualFlagType.MAINTENANCE:
                self.setText("Wartung")
                self.setStyleSheet(self._get_maintenance_style())
            else:  # CALCULATION_RUNNING
                self.setText("Berechnung")
                self.setStyleSheet(self._get_calculation_style())
            self.setEnabled(False)
            return

        if not self.workstation.can_connect(
            self.user.get_rdp_username(),
            self.user.windows_accounts(),
        ):
            self.setText("Belegt")
            self.setStyleSheet(self._get_disabled_style())
            self.setEnabled(False)
            if self.workstation.can_choose_session():
                self.setText("Sitzung öffnen …")
                self.setStyleSheet(self._get_normal_style())
                self.setEnabled(True)
        elif (
            self.workstation.matching_sessions(self.user.get_rdp_username())
            or self.workstation.owned_sessions(self.user.windows_accounts())
        ):
            self.setText("Wiederverbinden")
            self.setStyleSheet(self._get_connected_style())
            self.setEnabled(True)
        else:
            self.setText("Verbinden")
            self.setStyleSheet(self._get_normal_style())
            self.setEnabled(True)

    def _get_normal_style(self) -> str:
        """Get style sheet for normal connect button."""
        return DesignSystem.styles.button_primary()

    def _get_connected_style(self) -> str:
        """Get style sheet for connected state."""
        return f"""
            QPushButton {{
                background-color: {Colors.success.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.success.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: #2f5f3f;
                border-color: #2f5f3f;
            }}
            QPushButton:pressed {{
                background-color: #1f4f2f;
                border-color: #1f4f2f;
            }}
        """

    def _get_blocked_style(self) -> str:
        """Get style sheet for blocked state."""
        return f"""
            QPushButton {{
                background-color: {Colors.error.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.error.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """

    def _get_maintenance_style(self) -> str:
        """Get style sheet for maintenance state."""
        return f"""
            QPushButton {{
                background-color: {Colors.warning.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.warning.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """

    def _get_calculation_style(self) -> str:
        """Get style sheet for calculation running state."""
        return f"""
            QPushButton {{
                background-color: {Colors.info.name()};
                color: {Colors.surface.name()};
                border: 1px solid {Colors.info.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """

    def _get_disabled_style(self) -> str:
        """Get style sheet for disabled state."""
        return f"""
            QPushButton {{
                background-color: {Colors.surface_alt.name()};
                color: {Colors.text_muted.name()};
                border: 1px solid {Colors.border.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """

    def _on_clicked(self) -> None:
        """Handle button click."""
        self.connect_requested.emit(self.workstation)

    def update_workstation(self, workstation: Workstation) -> None:
        """Update the workstation and refresh appearance."""
        self.workstation = workstation
        self._update_appearance()


__all__ = ["ConnectButton"]
