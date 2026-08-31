"""Workstation model for Kirschke RDP Workstation Portal."""

from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from shared.enums import AgentStatus, ConnectionTargetMode, SessionState, ManualFlagType
from shared.schemas import WorkstationSchema, RDPProfileSchema, ManualFlagSchema
from shared.validation import generate_test_entra_id, generate_test_upn


@dataclass
class Workstation:
    """Local workstation model used in the portal application.
    
    This model represents a workstation with all its properties,
    including RDP profile, agent status, session state, and manual flags.
    """
    
    workstation_id: str
    display_name: str
    hostname: str
    fqdn: Optional[str] = None
    ip_address: Optional[str] = None
    subnet_mask: Optional[str] = None
    default_gateway: Optional[str] = None
    dns_server: Optional[str] = None
    connection_target_mode: ConnectionTargetMode = ConnectionTargetMode.AUTO
    site: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    
    # RDP Profile
    username_hint: Optional[str] = None
    entra_sso_enabled: bool = False
    trust_unverified_server: bool = False
    gateway_hostname: Optional[str] = None
    use_all_monitors: bool = False
    redirect_clipboard: bool = True
    redirect_drives: bool = False
    redirect_printers: bool = False
    redirect_audio: bool = False
    screen_mode: Optional[str] = None
    resolution: Optional[str] = None
    allowed_entra_group_ids: list[str] = field(default_factory=list)
    rdp_access_users: list[str] = field(default_factory=list)
    
    # Manual Flag
    manual_flag_type: ManualFlagType = ManualFlagType.NONE
    manual_flag_reason: Optional[str] = None
    manual_flag_project: Optional[str] = None
    manual_flag_set_by_object_id: Optional[str] = None
    manual_flag_set_by_upn: Optional[str] = None
    manual_flag_set_at_utc: Optional[datetime] = None
    manual_flag_expires_at_utc: Optional[datetime] = None
    
    # Agent Status
    agent_status: AgentStatus = AgentStatus.OFFLINE
    agent_last_seen_utc: Optional[datetime] = None
    agent_version: Optional[str] = None
    
    # Current Session
    current_session_state: SessionState = SessionState.NONE
    current_session_user: Optional[str] = None
    current_windows_session_id: Optional[int] = None
    last_session_event_utc: Optional[datetime] = None
    
    # SharePoint metadata
    etag: Optional[str] = None
    
    # UI state
    is_selected: bool = False
    
    def __post_init__(self):
        """Validate and initialize after creation."""
        # Ensure enums are properly set
        if isinstance(self.manual_flag_type, str):
            self.manual_flag_type = ManualFlagType(self.manual_flag_type)
        if isinstance(self.agent_status, str):
            self.agent_status = AgentStatus(self.agent_status)
        if isinstance(self.current_session_state, str):
            self.current_session_state = SessionState(self.current_session_state)
        if isinstance(self.connection_target_mode, str):
            self.connection_target_mode = ConnectionTargetMode(self.connection_target_mode)
    
    def to_schema(self) -> WorkstationSchema:
        """Convert to Pydantic schema."""
        return WorkstationSchema(
            workstation_id=self.workstation_id,
            display_name=self.display_name,
            hostname=self.hostname,
            fqdn=self.fqdn,
            ip_address=self.ip_address,
            subnet_mask=self.subnet_mask,
            default_gateway=self.default_gateway,
            dns_server=self.dns_server,
            connection_target_mode=self.connection_target_mode,
            site=self.site,
            description=self.description,
            enabled=self.enabled,
            allowed_entra_group_ids=self.allowed_entra_group_ids,
            rdp_access_users=self.rdp_access_users,
            username_hint=self.username_hint,
            entra_sso_enabled=self.entra_sso_enabled,
            trust_unverified_server=self.trust_unverified_server,
            gateway_hostname=self.gateway_hostname,
            use_all_monitors=self.use_all_monitors,
            redirect_clipboard=self.redirect_clipboard,
            redirect_drives=self.redirect_drives,
            redirect_printers=self.redirect_printers,
            redirect_audio=self.redirect_audio,
            screen_mode=self.screen_mode,
            resolution=self.resolution,
            manual_flag=ManualFlagSchema(
                flag_type=self.manual_flag_type,
                reason=self.manual_flag_reason,
                project=self.manual_flag_project,
                set_by_object_id=self.manual_flag_set_by_object_id,
                set_by_upn=self.manual_flag_set_by_upn,
                set_at_utc=self.manual_flag_set_at_utc,
                expires_at_utc=self.manual_flag_expires_at_utc,
            ),
            agent_status=self.agent_status,
            agent_last_seen_utc=self.agent_last_seen_utc,
            agent_version=self.agent_version,
            current_session_state=self.current_session_state,
            current_session_user=self.current_session_user,
            current_windows_session_id=self.current_windows_session_id,
            last_session_event_utc=self.last_session_event_utc,
            etag=self.etag,
        )
    
    @classmethod
    def from_schema(cls, schema: WorkstationSchema) -> "Workstation":
        """Create from Pydantic schema."""
        return cls(
            workstation_id=schema.workstation_id,
            display_name=schema.display_name,
            hostname=schema.hostname,
            fqdn=schema.fqdn,
            ip_address=schema.ip_address,
            subnet_mask=schema.subnet_mask,
            default_gateway=schema.default_gateway,
            dns_server=schema.dns_server,
            connection_target_mode=schema.connection_target_mode,
            site=schema.site,
            description=schema.description,
            enabled=schema.enabled,
            allowed_entra_group_ids=schema.allowed_entra_group_ids,
            rdp_access_users=schema.rdp_access_users,
            username_hint=schema.username_hint,
            entra_sso_enabled=schema.entra_sso_enabled,
            trust_unverified_server=schema.trust_unverified_server,
            gateway_hostname=schema.gateway_hostname,
            use_all_monitors=schema.use_all_monitors,
            redirect_clipboard=schema.redirect_clipboard,
            redirect_drives=schema.redirect_drives,
            redirect_printers=schema.redirect_printers,
            redirect_audio=schema.redirect_audio,
            screen_mode=schema.screen_mode,
            resolution=schema.resolution,
            manual_flag_type=schema.manual_flag.flag_type,
            manual_flag_reason=schema.manual_flag.reason,
            manual_flag_project=schema.manual_flag.project,
            manual_flag_set_by_object_id=schema.manual_flag.set_by_object_id,
            manual_flag_set_by_upn=schema.manual_flag.set_by_upn,
            manual_flag_set_at_utc=schema.manual_flag.set_at_utc,
            manual_flag_expires_at_utc=schema.manual_flag.expires_at_utc,
            agent_status=schema.agent_status,
            agent_last_seen_utc=schema.agent_last_seen_utc,
            agent_version=schema.agent_version,
            current_session_state=schema.current_session_state,
            current_session_user=schema.current_session_user,
            current_windows_session_id=schema.current_windows_session_id,
            last_session_event_utc=schema.last_session_event_utc,
            etag=schema.etag,
        )
    
    def get_rdp_profile(self, default_username: Optional[str] = None) -> RDPProfileSchema:
        """Get the RDP profile for this workstation."""
        return RDPProfileSchema(
            hostname=self.hostname,
            fqdn=self.fqdn,
            ip_address=self.ip_address,
            connection_target_mode=self.connection_target_mode,
            display_name=self.display_name,
            site=self.site,
            description=self.description,
            username_hint=self.username_hint or default_username,
            entra_sso_enabled=self.entra_sso_enabled,
            trust_unverified_server=self.trust_unverified_server,
            gateway_hostname=self.gateway_hostname,
            use_all_monitors=self.use_all_monitors,
            redirect_clipboard=self.redirect_clipboard,
            redirect_drives=self.redirect_drives,
            redirect_printers=self.redirect_printers,
            redirect_audio=self.redirect_audio,
            screen_mode=self.screen_mode,
            resolution=self.resolution,
            enabled=self.enabled,
            allowed_entra_group_ids=self.allowed_entra_group_ids,
        )

    def get_connection_target(self) -> tuple[str, ConnectionTargetMode]:
        """Return the concrete target and the address source used by RDP."""
        return self.get_rdp_profile().resolve_connection_target()

    def get_connection_target_display(self) -> str:
        labels = {
            ConnectionTargetMode.IP_ADDRESS: "IP-Adresse",
            ConnectionTargetMode.HOSTNAME: "Hostname",
            ConnectionTargetMode.FQDN: "FQDN",
        }
        try:
            target, mode = self.get_connection_target()
            configured = "Automatisch → " if self.connection_target_mode == ConnectionTargetMode.AUTO else ""
            return f"{configured}{labels[mode]} · {target}"
        except ValueError:
            return "Kein gültiges Ziel"
    
    def is_blocked(self) -> bool:
        """Check if workstation is blocked by a manual flag."""
        return self.manual_flag_type in [
            ManualFlagType.BLOCKED,
            ManualFlagType.MAINTENANCE,
            ManualFlagType.CALCULATION_RUNNING,
        ]
    
    def can_connect(self) -> bool:
        """Check if connection is allowed."""
        if not self.enabled:
            return False
        return not self.is_blocked() and not self.has_active_session()

    def has_active_session(self) -> bool:
        """Treat connected and disconnected Windows sessions as occupied."""
        return self.current_session_state not in [SessionState.NONE, SessionState.LOGGED_OFF]
    
    def can_disconnect(self) -> bool:
        """Check if disconnect is allowed (always for calculation_running)."""
        if self.manual_flag_type == ManualFlagType.CALCULATION_RUNNING:
            return True
        return not self.is_blocked()
    
    def can_logoff(self, is_admin: bool = False) -> bool:
        """Check if logoff is allowed."""
        if is_admin:
            return True  # Admins can always logoff with override
        return not self.is_blocked()
    
    def can_set_flag(self, flag_type: ManualFlagType, is_admin: bool = False) -> bool:
        """Check if a flag can be set."""
        if is_admin:
            return True
        
        # Users can only set calculation_running flag
        if flag_type == ManualFlagType.CALCULATION_RUNNING:
            return True
        
        return False
    
    def can_clear_flag(self, is_admin: bool = False, is_owner: bool = False) -> bool:
        """Check if a flag can be cleared."""
        if is_admin:
            return True
        
        # Users can clear their own flags
        if is_owner:
            return True
        
        return False
    
    def get_status_display(self) -> str:
        """Get a human-readable status display."""
        if not self.enabled:
            return "Deaktiviert"
        
        if self.is_blocked():
            flag_names = {
                ManualFlagType.CALCULATION_RUNNING: "Berechnung laeuft",
                ManualFlagType.MAINTENANCE: "Wartung",
                ManualFlagType.BLOCKED: "Gesperrt",
            }
            return flag_names.get(self.manual_flag_type, "Gesperrt")
        
        # Return session state
        state_names = {
            SessionState.NONE: "Bereit",
            SessionState.LOGON: "Anmeldung",
            SessionState.CONNECTED: "Verbunden",
            SessionState.RECONNECTED: "Wiederverbunden",
            SessionState.DISCONNECTED: "Getrennt",
            SessionState.LOGGED_OFF: "Abgemeldet",
        }
        return state_names.get(self.current_session_state, "Unbekannt")
    
    def get_agent_status_display(self) -> str:
        """Get a human-readable agent status display."""
        status_names = {
            AgentStatus.ONLINE: "Online",
            AgentStatus.STALE: "Veraltet",
            AgentStatus.OFFLINE: "Offline",
            AgentStatus.ERROR: "Fehler",
        }
        return status_names.get(self.agent_status, "Unbekannt")
    
    def get_session_user_display(self) -> str:
        """Get display text for current session user."""
        if self.current_session_user:
            return self.current_session_user
        return "-"


def create_mock_workstations(count: int = 10) -> list[Workstation]:
    """Create mock workstations for development and testing.
    
    Args:
        count: Number of workstations to create
        
    Returns:
        List of Workstation objects with mock data
    """
    workstations = []
    sites = ["Berlin", "Hamburg", "Munchen", "Frankfurt"]
    descriptions = [
        "Buroarbeitsplatz",
        "Berechnungs-Workstation",
        "Entwicklungsrechner",
        "Testsystem",
    ]
    
    for i in range(1, count + 1):
        site = sites[(i - 1) % len(sites)]
        
        # Vary the status and flags
        agent_statuses = [AgentStatus.ONLINE, AgentStatus.ONLINE, AgentStatus.STALE, AgentStatus.OFFLINE]
        session_states = [SessionState.NONE, SessionState.CONNECTED, SessionState.DISCONNECTED]
        
        agent_status = agent_statuses[(i - 1) % len(agent_statuses)]
        session_state = session_states[(i - 1) % len(session_states)]
        
        # Every 4th workstation has a flag
        flag_type = ManualFlagType.NONE
        if i % 4 == 0:
            flag_types = [ManualFlagType.CALCULATION_RUNNING, ManualFlagType.MAINTENANCE, ManualFlagType.BLOCKED]
            flag_type = flag_types[(i // 4) % len(flag_types)]
        
        workstation = Workstation(
            workstation_id=f"WS-{i:03d}",
            display_name=f"Workstation {i:03d}",
            hostname=f"ws{i:03d}.kirschke.local",
            fqdn=f"ws{i:03d}.buero.prof-kirschke.de",
            ip_address=f"192.168.{10 + ((i - 1) // 50)}.{20 + i}",
            subnet_mask="255.255.255.0",
            default_gateway=f"192.168.{10 + ((i - 1) // 50)}.1",
            dns_server="192.168.10.10",
            site=site,
            description=descriptions[(i - 1) % len(descriptions)],
            enabled=True,
            username_hint=f"user{i}@prof-kirschke.de",
            entra_sso_enabled=True,
            use_all_monitors=True,
            redirect_clipboard=True,
            
            manual_flag_type=flag_type,
            manual_flag_reason="Berechnung fur Projekt XYZ" if flag_type != ManualFlagType.NONE else None,
            manual_flag_project="Projekt XYZ" if flag_type != ManualFlagType.NONE else None,
            manual_flag_set_by_object_id=generate_test_entra_id(),
            manual_flag_set_by_upn=generate_test_upn(),
            manual_flag_set_at_utc=datetime.now() - timedelta(hours=2) if flag_type != ManualFlagType.NONE else None,
            
            agent_status=agent_status,
            agent_last_seen_utc=datetime.now() - timedelta(minutes=5) if agent_status == AgentStatus.ONLINE else None,
            agent_version="1.0.0",
            
            current_session_state=session_state,
            current_session_user=generate_test_upn() if session_state != SessionState.NONE else None,
            current_windows_session_id=1 if session_state != SessionState.NONE else None,
            last_session_event_utc=datetime.now() - timedelta(hours=1) if session_state != SessionState.NONE else None,
        )
        workstations.append(workstation)
    
    return workstations


def create_initial_workstations() -> list[Workstation]:
    """Create the two meaningful default machines for a fresh local portal."""
    return [
        Workstation(
            workstation_id="WS-001",
            display_name="Arbeitsplatz München",
            hostname="pc-muc-01",
            fqdn="pc-muc-01.kirschke.local",
            ip_address="192.168.10.21",
            subnet_mask="255.255.255.0",
            default_gateway="192.168.10.1",
            dns_server="192.168.10.10",
            site="München",
            description="Standard-Arbeitsplatz",
            enabled=True,
            agent_status=AgentStatus.ONLINE,
            agent_last_seen_utc=datetime.now(),
        ),
        Workstation(
            workstation_id="WS-002",
            display_name="Arbeitsplatz Ettlingen",
            hostname="pc-ett-01",
            fqdn="pc-ett-01.kirschke.local",
            ip_address="192.168.20.21",
            subnet_mask="255.255.255.0",
            default_gateway="192.168.20.1",
            dns_server="192.168.20.10",
            site="Ettlingen",
            description="Standard-Arbeitsplatz",
            enabled=True,
            agent_status=AgentStatus.ONLINE,
            agent_last_seen_utc=datetime.now(),
        ),
    ]


def create_test_workstation() -> Workstation:
    """Create a single test workstation."""
    return create_mock_workstations(1)[0]


__all__ = [
    "Workstation",
    "create_initial_workstations",
    "create_mock_workstations",
    "create_test_workstation",
]
