"""UI components for Kirschke RDP Workstation Portal."""

from portal_app.ui.design import Colors, DesignSystem, Typography
from portal_app.ui.main_window import MainWindow
from portal_app.ui.widgets import (
    ConnectButton,
    FlagDialog,
    SessionLogWidget,
    StatusBadgeWidget,
    WorkstationCardsWidget,
    WorkstationDetailWidget,
    WorkstationTableWidget,
)

__all__ = [
    "MainWindow",
    "DesignSystem",
    "Colors",
    "Typography",
    "WorkstationTableWidget",
    "WorkstationDetailWidget",
    "SessionLogWidget",
    "StatusBadgeWidget",
    "FlagDialog",
    "ConnectButton",
    "WorkstationCardsWidget",
]
