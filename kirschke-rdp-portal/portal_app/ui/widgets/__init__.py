"""UI widgets for Kirschke RDP Workstation Portal."""

from portal_app.ui.widgets.connect_button import ConnectButton
from portal_app.ui.widgets.flag_dialog import FlagDialog
from portal_app.ui.widgets.management_pages import AdministrationWidget, SettingsWidget
from portal_app.ui.widgets.ping_tool import PingToolWidget
from portal_app.ui.widgets.rdp_access_dialog import RDPAccessDialog
from portal_app.ui.widgets.reservation_calendar import ReservationCalendarWidget
from portal_app.ui.widgets.session_log import SessionLogWidget
from portal_app.ui.widgets.status_badge import StatusBadgeWidget
from portal_app.ui.widgets.user_settings_dialog import UserSettingsDialog
from portal_app.ui.widgets.workstation_cards import WorkstationCardsWidget
from portal_app.ui.widgets.workstation_detail import WorkstationDetailWidget
from portal_app.ui.widgets.workstation_dialog import WorkstationDialog
from portal_app.ui.widgets.workstation_table import WorkstationTableWidget

__all__ = [
    "WorkstationTableWidget",
    "WorkstationDetailWidget",
    "SessionLogWidget",
    "StatusBadgeWidget",
    "FlagDialog",
    "ConnectButton",
    "WorkstationCardsWidget",
    "WorkstationDialog",
    "UserSettingsDialog",
    "ReservationCalendarWidget",
    "AdministrationWidget",
    "SettingsWidget",
    "PingToolWidget",
    "RDPAccessDialog",
]
