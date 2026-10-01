"""Connect button widget for Kirschke RDP Workstation Portal."""


from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton

from portal_app.models.user import User
from portal_app.models.workstation import Workstation
from portal_app.ui.design import Colors, DesignSystem, scaled
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
        self.setMinimumWidth(scaled(130))
        self.setMinimumHeight(scaled(30))

        # Update appearance based on status
        self._update_appearance()

        # Connect click
        self.clicked.connect(self._on_clicked)

    def _update_appearance(self) -> None:
        """Beschriftung, Farbe und Klickbarkeit aus dem einen Maschinenzustand.

        Diese Entscheidung stand hier früher ein zweites Mal, mit eigenen
        Bedingungen -- genau die Doppelung, die machine_actions abschaffen
        sollte. Sie war schon auseinandergelaufen: Karte und Detailseite boten
        "Trotzdem verbinden" an, während die Tabelle weiter "Belegt" ausgraute.
        """
        from portal_app.ui.machine_actions import describe_actions

        actions = describe_actions(self.workstation, self.user)
        self.setText(actions.primary_text)
        self.setToolTip(actions.primary_tooltip)
        self.setEnabled(actions.primary_enabled)
        self.setStyleSheet(self._style_for(actions.state))

    def _style_for(self, state) -> str:
        """Die Farbe zum Zustand, damit die Tabelle dasselbe zeigt wie die Karte."""
        from portal_app.ui.machine_actions import MachineState

        if state is MachineState.BLOCKED:
            flag = self.workstation.manual_flag_type
            if flag == ManualFlagType.BLOCKED:
                return self._get_blocked_style()
            return (
                self._get_maintenance_style()
                if flag == ManualFlagType.MAINTENANCE
                else self._get_calculation_style()
            )
        if state in (MachineState.OWN_IDLE, MachineState.OCCUPIED_SELF):
            return self._get_connected_style()
        if state in (MachineState.DISABLED, MachineState.UNKNOWN):
            return self._get_disabled_style()
        if state in (
            MachineState.OCCUPIED_OTHER,
            MachineState.OCCUPIED_OTHER_IDLE,
            MachineState.RESERVED,
        ):
            # Klickbar, aber sichtbar nicht der normale Weg: Die Warnung
            # kommt erst nach dem Klick, die Farbe schon davor.
            return self._get_taken_style()
        return self._get_normal_style()

    def _get_taken_style(self) -> str:
        """Style für eine belegte Maschine, die man trotzdem anfassen darf."""
        return f"""
            QPushButton {{
                background-color: {Colors.surface.name()};
                color: {Colors.taken.name()};
                border: 1px solid {Colors.taken.name()};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QPushButton:hover {{
                background-color: {Colors.surface_alt.name()};
            }}
        """

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
