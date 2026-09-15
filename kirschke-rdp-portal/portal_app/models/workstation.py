"""Workstation model for Kirschke RDP Workstation Portal."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from shared.enums import AgentStatus, ConnectionTargetMode, ManualFlagType, SessionState
from shared.identity import ENTRA_DOMAIN, IdentityMatch, WindowsIdentity
from shared.schemas import ManualFlagSchema, RDPProfileSchema, WorkstationSchema
from shared.session_identity import is_active_session, session_username
from shared.validation import generate_test_entra_id, generate_test_upn


def as_windows_identity(value: WindowsIdentity | str | None) -> WindowsIdentity | None:
    r"""Accept either a typed identity or a bare ``DOMAIN\user`` string."""
    if isinstance(value, WindowsIdentity):
        return value
    identity = WindowsIdentity.from_names(down_level=value)
    return identity if identity.for_display() else None


#: One account, several, in either spelling, or none at all.
OwnAccounts = WindowsIdentity | str | Iterable[WindowsIdentity | str] | None


def as_windows_identities(value: OwnAccounts) -> list[WindowsIdentity]:
    """Accept one account or several, in either spelling.

    A person can legitimately hold more than one Windows account -- the Entra one
    plus a local account on a lab machine, say -- and a session of any of them is
    still their session.
    """
    if value is None:
        return []
    if isinstance(value, WindowsIdentity | str):
        value = [value]
    resolved = [as_windows_identity(item) for item in value]
    return [identity for identity in resolved if identity is not None]


@dataclass
class Workstation:
    """Local workstation model used in the portal application.

    This model represents a workstation with all its properties,
    including RDP profile, agent status, session state, and manual flags.
    """

    workstation_id: str
    display_name: str
    hostname: str
    fqdn: str | None = None
    ip_address: str | None = None
    subnet_mask: str | None = None
    default_gateway: str | None = None
    dns_server: str | None = None
    connection_target_mode: ConnectionTargetMode = ConnectionTargetMode.AUTO
    site: str | None = None
    description: str | None = None
    enabled: bool = True

    # RDP Profile
    username_hint: str | None = None
    entra_sso_enabled: bool = False
    trust_unverified_server: bool = False
    gateway_hostname: str | None = None
    use_all_monitors: bool = False
    redirect_clipboard: bool = True
    redirect_drives: bool = False
    redirect_printers: bool = False
    redirect_audio: bool = False
    screen_mode: str | None = None
    resolution: str | None = None
    allowed_entra_group_ids: list[str] = field(default_factory=list)
    rdp_access_users: list[str] = field(default_factory=list)
    login_accounts: list[str] = field(default_factory=list)
    # This choice belongs to the local portal user, not shared machine settings.
    selected_login_account: str | None = None
    reservation_message: str = ""  # transient, evaluated for the current portal user
    reservation_block_reason: str = ""

    # Manual Flag
    manual_flag_type: ManualFlagType = ManualFlagType.NONE
    manual_flag_reason: str | None = None
    manual_flag_project: str | None = None
    manual_flag_set_by_object_id: str | None = None
    manual_flag_set_by_upn: str | None = None
    manual_flag_set_at_utc: datetime | None = None
    manual_flag_expires_at_utc: datetime | None = None

    # Agent Status
    agent_workstation_id: str | None = None
    agent_sessions: list[dict] = field(default_factory=list)  # transient snapshot data
    # Reservierungen, die der Agent dieser Maschine gemeldet hat. Ebenfalls
    # fluechtig: die eigene Wahrheit des Portals steht in LocalStore.
    # None heisst "nicht gemeldet" (Agent aelter als 1.5.0 oder nicht
    # erreichbar) und ist etwas anderes als eine leere Liste.
    agent_reservations: list[dict] | None = None
    agent_session_history: list[dict] = field(default_factory=list)
    agent_status: AgentStatus = AgentStatus.OFFLINE
    agent_last_seen_utc: datetime | None = None
    agent_version: str | None = None
    agent_diagnostic: str = "Noch keine Agent-Prüfung"  # local display only
    agent_status_source: str = "none"  # transient: live, file or none
    agent_live_error: str | None = None  # transient; never confirms old data as current
    # Client-local setting. SMB credentials and reachable paths can differ per
    # portal PC, so this intentionally is not part of the shared machine schema.
    agent_fallback_directory: str | None = None
    agent_fallback_is_explicit: bool = False

    # Current Session
    current_session_state: SessionState = SessionState.NONE
    current_session_user: str | None = None
    current_windows_session_id: int | None = None
    last_session_event_utc: datetime | None = None

    # SharePoint metadata
    etag: str | None = None

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
            login_accounts=self.login_accounts,
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
            agent_workstation_id=self.agent_workstation_id,
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
            login_accounts=schema.login_accounts,
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
            agent_workstation_id=schema.agent_workstation_id,
            current_session_state=schema.current_session_state,
            current_session_user=schema.current_session_user,
            current_windows_session_id=schema.current_windows_session_id,
            last_session_event_utc=schema.last_session_event_utc,
            etag=schema.etag,
        )

    def get_rdp_profile(self, default_username: str | None = None) -> RDPProfileSchema:
        """Get the RDP profile for this workstation."""
        return RDPProfileSchema(
            hostname=self.hostname,
            fqdn=self.fqdn,
            ip_address=self.ip_address,
            connection_target_mode=self.connection_target_mode,
            display_name=self.display_name,
            site=self.site,
            description=self.description,
            username_hint=self.selected_login_account or self.username_hint or default_username,
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
        """Return the concrete target and the address source used by RDP.

        This is the portal-side entry point, so it asks whether an identifier
        can actually be resolved instead of only preferring one. The answers
        are cached, and a machine with a single identifier is decided without
        any lookup at all.
        """
        from shared.name_resolution import resolvable

        return self.get_rdp_profile().resolve_connection_target(resolvable)

    def get_agent_status_target(self) -> str:
        """Return the SMB server identity authenticated for this agent channel.

        RDP can deliberately use an IP address when the Windows hostname is not
        resolvable.  A per-machine fallback connection may nevertheless be
        authenticated under that hostname.  Reusing its UNC server keeps the
        read-only named pipe in the same Windows SMB logon session.
        """
        from shared.name_resolution import resolvable

        configured = (self.agent_fallback_directory or "").strip()
        if self.agent_fallback_is_explicit:
            match = re.match(r"^\\\\([^\\]+)\\", configured)
            # The share is often written with the Windows name while RDP has
            # already had to move to the IP address. That name then does not
            # resolve either, and insisting on it costs the live status of a
            # perfectly reachable machine -- so fall through to the RDP target,
            # which has just been checked the same way.
            if match and resolvable(match.group(1)):
                return match.group(1)
        target, _ = self.get_connection_target()
        return target

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

    def session_accounts(self) -> list[str]:
        from shared.login_accounts import validate_login_account
        values = [
            session_username(item)
            for item in self.agent_sessions
            if is_active_session(item)
        ]
        if self.has_active_session() and self.current_session_user:
            values.append(self.current_session_user)
        result = {}
        for value in values:
            try:
                value = validate_login_account(value)
                result.setdefault(value.casefold(), value)
            except ValueError:
                continue
        return list(result.values())

    def reports_entra_sessions(self) -> bool:
        """Whether the agent's own reports show this machine using Entra accounts."""
        return any(
            WindowsIdentity.from_session(item).is_entra for item in self.reported_sessions()
        )

    def entra_spelling_warning(self, default_username: str | None = None) -> str | None:
        r"""Explain a chosen account that this target cannot authenticate, or ``None``.

        The agent reports ``AzureAD\...`` sessions exactly when the machine signs
        people in with Entra accounts.  If the machine is not marked as an Entra
        target, the .rdp file carries a bare UPN and no web sign-in, so Windows
        authenticates something else -- and the target refuses the remote logon
        with "not authorized", even when the account is in the group.
        """
        if self.entra_sso_enabled or not self.reports_entra_sessions():
            return None
        account = self.selected_login_account or self.username_hint or default_username
        identity = WindowsIdentity.from_names(down_level=account)
        if not identity.upn or identity.down_level:
            return None
        return (
            f"{self.display_name} meldet Windows-Sitzungen mit Entra-Konten, ist im Portal "
            "aber nicht als Entra-Ziel eingestellt. Deshalb wird "
            f"„{identity.upn}“ ohne Entra-Anmeldung übergeben, und der Zielrechner lehnt die "
            "Remoteanmeldung als nicht autorisiert ab, obwohl das Konto freigeschaltet ist.\n\n"
            f"Richtig wäre die Entra-Anmeldung oder der Kontoname "
            f"„{ENTRA_DOMAIN}\\{identity.upn}“."
        )

    def can_choose_session(self) -> bool:
        return self.enabled and not self.is_blocked() and not self.reservation_block_reason and bool(self.session_accounts())

    def matching_sessions(self, default_username: str | None = None) -> list[dict]:
        """UI account matching only; Windows remains responsible for authentication."""
        account = (self.selected_login_account or self.username_hint or default_username or "").strip().casefold()
        return self.sessions_for_account(account)

    def reported_sessions(self) -> list[dict]:
        """Every session the agent reported, or one rebuilt from the summary fields."""
        sessions = list(self.agent_sessions)
        if not sessions and self.has_active_session():
            sessions = [{"session_id": self.current_windows_session_id,
                         "full_username": self.current_session_user,
                         "session_state": self.current_session_state.value}]
        return sessions

    def foreign_sessions(self, identity: OwnAccounts) -> list[dict]:
        """Active sessions that do not belong to the portal user."""
        own = {id(item) for item in self.owned_sessions(identity)}
        return [
            item
            for item in self.reported_sessions()
            if is_active_session(item) and id(item) not in own
        ]

    def foreign_session_is_idle(self, identity: OwnAccounts) -> bool:
        """Whether somebody else holds this machine without being connected to it.

        Closing an RDP window does not end the Windows session, it disconnects
        it -- the account keeps the machine while nobody is looking at it. That
        is the same situation ``OWN_IDLE`` marks for your own account, and it is
        worth showing for a colleague too: it is the machine where asking is
        likely to free something up.

        Read from what the agent reports rather than from a portal telling other
        portals about its windows. The agent sees the fact itself, which also
        covers a colleague who connected with plain ``mstsc``, and there is no
        flag left standing when somebody's portal simply disappears.
        """
        sessions = self.foreign_sessions(identity)
        return bool(sessions) and all(
            str(item.get("session_state") or "").casefold()
            == SessionState.DISCONNECTED.value
            for item in sessions
        )

    def sessions_for_account(self, account: str | None) -> list[dict]:
        """Return active sessions whose reported Windows name matches one account."""
        account = (account or "").strip().casefold()
        if not account:
            return []
        return [
            item
            for item in self.reported_sessions()
            if is_active_session(item) and session_username(item).strip().casefold() == account
        ]

    def owned_sessions(self, identity: OwnAccounts) -> list[dict]:
        """Active sessions belonging to any of the portal user's own accounts.

        Compares SIDs when the agent reported one, and falls back to comparing
        names otherwise -- see :meth:`owned_session_match` for which of the two
        decided.  Either way this is a UI hint: the agent authorizes a logoff
        independently and never trusts what the portal claims here.
        """
        accounts = as_windows_identities(identity)
        if not accounts:
            return []
        return [
            item
            for item in self.reported_sessions()
            if is_active_session(item)
            and any(account.matches(WindowsIdentity.from_session(item)) for account in accounts)
        ]

    def owned_session_match(self, identity: OwnAccounts) -> IdentityMatch:
        """The strongest way an own session could be recognised, for honest labels."""
        accounts = as_windows_identities(identity)
        if not accounts:
            return IdentityMatch.NO
        matches = [
            account.matches(WindowsIdentity.from_session(item))
            for item in self.reported_sessions()
            if is_active_session(item)
            for account in accounts
        ]
        if any(match.is_proof for match in matches):
            return IdentityMatch.BY_SID
        return IdentityMatch.BY_NAME_UNVERIFIED if any(matches) else IdentityMatch.NO

    def can_connect(
        self,
        default_username: str | None = None,
        identity: OwnAccounts = None,
    ) -> bool:
        """Check if connection is allowed."""
        if not self.enabled or self.reservation_block_reason:
            return False
        return not self.is_blocked() and (
            not self.has_active_session()
            or bool(self.matching_sessions(default_username))
            or bool(self.owned_sessions(identity))
        )

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
        """Whether this flag may be set. Flags are an administrative statement.

        Regular users used to be allowed to set "Berechnung laeuft" on any machine.
        A reservation says the same thing better -- who holds the machine and until
        when -- so that exception is gone and flagging is administrative only.
        """
        return is_admin

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

    def get_agent_source_display(self, now: datetime | None = None) -> str:
        """Show where the currently displayed snapshot came from and how old it is."""
        if self.agent_last_seen_utc is None:
            return "Kein bestätigter Status"
        now = now or datetime.now(UTC)
        last_seen = self.agent_last_seen_utc
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        age = max(0, int((now - last_seen).total_seconds()))
        age_text = "gerade eben" if age < 2 else f"vor {age} Sekunden"
        if self.agent_status_source == "live":
            if self.agent_live_error:
                return f"Live nicht erreichbar · letzter Stand {age_text}"
            return f"Live · {age_text}"
        if self.agent_status_source == "file":
            return f"Datei-Fallback · {age_text}"
        return f"Unbestätigte Quelle · {age_text}"

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
