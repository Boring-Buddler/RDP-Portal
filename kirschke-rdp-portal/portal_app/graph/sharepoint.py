"""SharePoint list operations for Kirschke RDP Workstation Portal.

This module provides specialized operations for SharePoint lists used by the
RDP Workstation Portal:
- RDP_Workstations
- RDP_SessionEvents
- RDP_AdminCommands
- RDP_AccessRules

Features:
- ETag handling for optimistic concurrency control
- Schema validation and data conversion
- Mapping between SharePoint fields and portal data models
- Batch operations for efficiency
"""

import os
import json
import logging
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from portal_app.graph.client import (
    GraphClient,
    GraphClientConfig,
    GraphResponse,
    PaginatedResponse,
    GraphAPIError,
    GraphNotFoundError,
)
from portal_app.auth.entra_auth import EntraAuthProvider
from shared.schemas import (
    WorkstationSchema,
    SessionEventSchema,
    AdminCommandSchema,
    AccessRuleSchema,
    ManualFlagSchema,
)
from shared.enums import (
    AgentStatus,
    SessionState,
    ManualFlagType,
    EventType,
    EventResult,
    EventSource,
    CommandType,
    CommandStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class SharePointConfig:
    """Configuration for SharePoint integration."""
    
    site_id: str = os.getenv("SHAREPOINT_SITE_ID", "")
    site_url: str = os.getenv("SHAREPOINT_SITE_URL", "")
    
    # List names
    workstations_list: str = os.getenv("SHAREPOINT_WORKSTATIONS_LIST", "RDP_Workstations")
    sessions_list: str = os.getenv("SHAREPOINT_SESSIONS_LIST", "RDP_SessionEvents")
    commands_list: str = os.getenv("SHAREPOINT_COMMANDS_LIST", "RDP_AdminCommands")
    access_rules_list: str = os.getenv("SHAREPOINT_ACCESS_RULES_LIST", "RDP_AccessRules")
    
    @classmethod
    def from_env(cls) -> "SharePointConfig":
        """Create configuration from environment variables."""
        return cls(
            site_id=os.getenv("SHAREPOINT_SITE_ID", ""),
            site_url=os.getenv("SHAREPOINT_SITE_URL", ""),
            workstations_list=os.getenv("SHAREPOINT_WORKSTATIONS_LIST", "RDP_Workstations"),
            sessions_list=os.getenv("SHAREPOINT_SESSIONS_LIST", "RDP_SessionEvents"),
            commands_list=os.getenv("SHAREPOINT_COMMANDS_LIST", "RDP_AdminCommands"),
            access_rules_list=os.getenv("SHAREPOINT_ACCESS_RULES_LIST", "RDP_AccessRules"),
        )
    
    def validate(self) -> bool:
        """Validate configuration."""
        return bool(self.site_id or self.site_url)


# =============================================================================
# SharePoint Field Mappings
# =============================================================================

class SharePointFieldMappings:
    """Field mappings between portal models and SharePoint list columns."""
    
    # Workstation fields
    WORKSTATION_FIELDS = {
        "workstation_id": "WorkstationId",
        "display_name": "DisplayName",
        "hostname": "Hostname",
        "fqdn": "FQDN",
        "site": "Site",
        "description": "Description",
        "enabled": "Enabled",
        "username_hint": "UsernameHint",
        "entra_sso_enabled": "EntraSSOEnabled",
        "gateway_hostname": "GatewayHostname",
        "use_all_monitors": "UseAllMonitors",
        "redirect_clipboard": "RedirectClipboard",
        "redirect_drives": "RedirectDrives",
        "redirect_printers": "RedirectPrinters",
        "redirect_audio": "RedirectAudio",
        "screen_mode": "ScreenMode",
        "resolution": "Resolution",
        "allowed_entra_group_ids": "AllowedEntraGroupIds",
        "agent_status": "AgentStatus",
        "agent_last_seen_utc": "AgentLastSeenUtc",
        "agent_version": "AgentVersion",
        "current_session_state": "CurrentSessionState",
        "current_session_user": "CurrentSessionUser",
        "current_windows_session_id": "CurrentWindowsSessionId",
        "last_session_event_utc": "LastSessionEventUtc",
        "etag": "ETag",
        # Manual flag fields
        "manual_flag_flag_type": "ManualFlagType",
        "manual_flag_reason": "ManualFlagReason",
        "manual_flag_project": "ManualFlagProject",
        "manual_flag_set_by_object_id": "ManualFlagSetByObjectId",
        "manual_flag_set_by_upn": "ManualFlagSetByUpn",
        "manual_flag_set_at_utc": "ManualFlagSetAtUtc",
        "manual_flag_expires_at_utc": "ManualFlagExpiresAtUtc",
    }
    
    # Session event fields
    SESSION_EVENT_FIELDS = {
        "event_id": "EventId",
        "timestamp_utc": "TimestampUtc",
        "event_type": "EventType",
        "workstation_id": "WorkstationId",
        "workstation_hostname": "WorkstationHostname",
        "windows_session_id": "WindowsSessionId",
        "session_user_upn": "SessionUserUpn",
        "session_user_domain": "SessionUserDomain",
        "client_name": "ClientName",
        "client_ip": "ClientIp",
        "actor_entra_object_id": "ActorEntraObjectId",
        "actor_upn": "ActorUpn",
        "result": "Result",
        "reason": "Reason",
        "source": "Source",
        "correlation_id": "CorrelationId",
        "agent_version": "AgentVersion",
    }
    
    # Admin command fields
    ADMIN_COMMAND_FIELDS = {
        "command_id": "CommandId",
        "target_workstation_id": "TargetWorkstationId",
        "target_windows_session_id": "TargetWindowsSessionId",
        "command_type": "CommandType",
        "requested_by_object_id": "RequestedByObjectId",
        "requested_by_upn": "RequestedByUpn",
        "requested_at_utc": "RequestedAtUtc",
        "expires_at_utc": "ExpiresAtUtc",
        "reason": "Reason",
        "status": "Status",
        "executed_at_utc": "ExecutedAtUtc",
        "result_message": "ResultMessage",
    }
    
    # Access rule fields
    ACCESS_RULE_FIELDS = {
        "rule_id": "RuleId",
        "entra_user_or_group_id": "EntraUserOrGroupId",
        "workstation_id": "WorkstationId",
        "may_connect": "MayConnect",
        "may_set_calculation_flag": "MaySetCalculationFlag",
        "valid_from_utc": "ValidFromUtc",
        "valid_until_utc": "ValidUntilUtc",
        "enabled": "Enabled",
    }


# =============================================================================
# Data Converters
# =============================================================================

class SharePointDataConverter:
    """Convert between portal data models and SharePoint list items."""
    
    @staticmethod
    def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
        """Format datetime for SharePoint."""
        if dt is None:
            return None
        return dt.isoformat()
    
    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Parse datetime from SharePoint."""
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return None
        return None
    
    @staticmethod
    def _format_enum(enum_value: Any) -> Optional[str]:
        """Format enum value for SharePoint."""
        if enum_value is None:
            return None
        if isinstance(enum_value, Enum):
            return enum_value.value
        return str(enum_value)
    
    @staticmethod
    def _parse_enum(value: Any, enum_class: type[Enum], default: Enum) -> Enum:
        """Parse enum value from SharePoint."""
        if value is None:
            return default
        if isinstance(value, enum_class):
            return value
        try:
            return enum_class(value)
        except (ValueError, KeyError):
            return default
    
    @staticmethod
    def _format_list(values: list) -> Optional[str]:
        """Format list as JSON string for SharePoint."""
        if not values:
            return None
        return json.dumps(values)
    
    @staticmethod
    def _parse_list(value: Any) -> list:
        """Parse list from JSON string in SharePoint."""
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return []


class WorkstationConverter(SharePointDataConverter):
    """Convert WorkstationSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, workstation: WorkstationSchema) -> dict:
        """Convert WorkstationSchema to SharePoint list item."""
        fields = SharePointFieldMappings.WORKSTATION_FIELDS
        
        data: dict[str, Any] = {}
        
        # Basic fields
        data[fields["workstation_id"]] = workstation.workstation_id
        data[fields["display_name"]] = workstation.display_name
        data[fields["hostname"]] = workstation.hostname
        data[fields["fqdn"]] = workstation.fqdn
        data[fields["site"]] = workstation.site
        data[fields["description"]] = workstation.description
        data[fields["enabled"]] = workstation.enabled
        
        # RDP profile fields
        data[fields["username_hint"]] = workstation.username_hint
        data[fields["entra_sso_enabled"]] = workstation.entra_sso_enabled
        data[fields["gateway_hostname"]] = workstation.gateway_hostname
        data[fields["use_all_monitors"]] = workstation.use_all_monitors
        data[fields["redirect_clipboard"]] = workstation.redirect_clipboard
        data[fields["redirect_drives"]] = workstation.redirect_drives
        data[fields["redirect_printers"]] = workstation.redirect_printers
        data[fields["redirect_audio"]] = workstation.redirect_audio
        data[fields["screen_mode"]] = workstation.screen_mode
        data[fields["resolution"]] = workstation.resolution
        data[fields["allowed_entra_group_ids"]] = cls._format_list(workstation.allowed_entra_group_ids)
        
        # Agent status fields
        data[fields["agent_status"]] = cls._format_enum(workstation.agent_status)
        data[fields["agent_last_seen_utc"]] = cls._format_datetime(workstation.agent_last_seen_utc)
        data[fields["agent_version"]] = workstation.agent_version
        
        # Session state fields
        data[fields["current_session_state"]] = cls._format_enum(workstation.current_session_state)
        data[fields["current_session_user"]] = workstation.current_session_user
        data[fields["current_windows_session_id"]] = workstation.current_windows_session_id
        data[fields["last_session_event_utc"]] = cls._format_datetime(workstation.last_session_event_utc)
        
        # Manual flag fields
        flag = workstation.manual_flag
        data[fields["manual_flag_flag_type"]] = cls._format_enum(flag.flag_type)
        data[fields["manual_flag_reason"]] = flag.reason
        data[fields["manual_flag_project"]] = flag.project
        data[fields["manual_flag_set_by_object_id"]] = flag.set_by_object_id
        data[fields["manual_flag_set_by_upn"]] = flag.set_by_upn
        data[fields["manual_flag_set_at_utc"]] = cls._format_datetime(flag.set_at_utc)
        data[fields["manual_flag_expires_at_utc"]] = cls._format_datetime(flag.expires_at_utc)
        
        return data
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> WorkstationSchema:
        """Convert SharePoint list item to WorkstationSchema."""
        fields = SharePointFieldMappings.WORKSTATION_FIELDS
        
        # Extract fields with proper types
        def get_field(field_name: str, default: Any = None) -> Any:
            sp_field = fields.get(field_name)
            if sp_field and sp_field in item:
                return item[sp_field]
            return default
        
        manual_flag = ManualFlagSchema(
            flag_type=cls._parse_enum(
                get_field("manual_flag_flag_type"),
                ManualFlagType,
                ManualFlagType.NONE
            ),
            reason=get_field("manual_flag_reason"),
            project=get_field("manual_flag_project"),
            set_by_object_id=get_field("manual_flag_set_by_object_id"),
            set_by_upn=get_field("manual_flag_set_by_upn"),
            set_at_utc=cls._parse_datetime(get_field("manual_flag_set_at_utc")),
            expires_at_utc=cls._parse_datetime(get_field("manual_flag_expires_at_utc")),
        )
        
        return WorkstationSchema(
            workstation_id=get_field("workstation_id", ""),
            display_name=get_field("display_name", ""),
            hostname=get_field("hostname", ""),
            fqdn=get_field("fqdn"),
            site=get_field("site"),
            description=get_field("description"),
            enabled=get_field("enabled", True),
            username_hint=get_field("username_hint"),
            entra_sso_enabled=get_field("entra_sso_enabled", False),
            gateway_hostname=get_field("gateway_hostname"),
            use_all_monitors=get_field("use_all_monitors", False),
            redirect_clipboard=get_field("redirect_clipboard", True),
            redirect_drives=get_field("redirect_drives", False),
            redirect_printers=get_field("redirect_printers", False),
            redirect_audio=get_field("redirect_audio", False),
            screen_mode=get_field("screen_mode"),
            resolution=get_field("resolution"),
            allowed_entra_group_ids=cls._parse_list(get_field("allowed_entra_group_ids", [])),
            agent_status=cls._parse_enum(
                get_field("agent_status"),
                AgentStatus,
                AgentStatus.OFFLINE
            ),
            agent_last_seen_utc=cls._parse_datetime(get_field("agent_last_seen_utc")),
            agent_version=get_field("agent_version"),
            current_session_state=cls._parse_enum(
                get_field("current_session_state"),
                SessionState,
                SessionState.NONE
            ),
            current_session_user=get_field("current_session_user"),
            current_windows_session_id=get_field("current_windows_session_id"),
            last_session_event_utc=cls._parse_datetime(get_field("last_session_event_utc")),
            manual_flag=manual_flag,
            etag=item.get("etag") or item.get("@odata.etag"),
        )


class SessionEventConverter(SharePointDataConverter):
    """Convert SessionEventSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, event: SessionEventSchema) -> dict:
        """Convert SessionEventSchema to SharePoint list item."""
        fields = SharePointFieldMappings.SESSION_EVENT_FIELDS
        
        data: dict[str, Any] = {}
        
        data[fields["event_id"]] = event.event_id
        data[fields["timestamp_utc"]] = cls._format_datetime(event.timestamp_utc)
        data[fields["event_type"]] = cls._format_enum(event.event_type)
        data[fields["workstation_id"]] = event.workstation_id
        data[fields["workstation_hostname"]] = event.workstation_hostname
        data[fields["windows_session_id"]] = event.windows_session_id
        data[fields["session_user_upn"]] = event.session_user_upn
        data[fields["session_user_domain"]] = event.session_user_domain
        data[fields["client_name"]] = event.client_name
        data[fields["client_ip"]] = event.client_ip
        data[fields["actor_entra_object_id"]] = event.actor_entra_object_id
        data[fields["actor_upn"]] = event.actor_upn
        data[fields["result"]] = cls._format_enum(event.result)
        data[fields["reason"]] = event.reason
        data[fields["source"]] = cls._format_enum(event.source)
        data[fields["correlation_id"]] = event.correlation_id
        data[fields["agent_version"]] = event.agent_version
        
        return data
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> SessionEventSchema:
        """Convert SharePoint list item to SessionEventSchema."""
        fields = SharePointFieldMappings.SESSION_EVENT_FIELDS
        
        def get_field(field_name: str, default: Any = None) -> Any:
            sp_field = fields.get(field_name)
            if sp_field and sp_field in item:
                return item[sp_field]
            return default
        
        return SessionEventSchema(
            event_id=get_field("event_id", ""),
            timestamp_utc=cls._parse_datetime(get_field("timestamp_utc")) or datetime.utcnow(),
            event_type=cls._parse_enum(
                get_field("event_type"),
                EventType,
                EventType.LAUNCH_REQUESTED
            ),
            workstation_id=get_field("workstation_id", ""),
            workstation_hostname=get_field("workstation_hostname"),
            windows_session_id=get_field("windows_session_id"),
            session_user_upn=get_field("session_user_upn"),
            session_user_domain=get_field("session_user_domain"),
            client_name=get_field("client_name"),
            client_ip=get_field("client_ip"),
            actor_entra_object_id=get_field("actor_entra_object_id"),
            actor_upn=get_field("actor_upn"),
            result=cls._parse_enum(
                get_field("result"),
                EventResult,
                EventResult.PENDING
            ),
            reason=get_field("reason"),
            source=cls._parse_enum(
                get_field("source"),
                EventSource,
                EventSource.PORTAL
            ),
            correlation_id=get_field("correlation_id"),
            agent_version=get_field("agent_version"),
        )


class AdminCommandConverter(SharePointDataConverter):
    """Convert AdminCommandSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, command: AdminCommandSchema) -> dict:
        """Convert AdminCommandSchema to SharePoint list item."""
        fields = SharePointFieldMappings.ADMIN_COMMAND_FIELDS
        
        data: dict[str, Any] = {}
        
        data[fields["command_id"]] = command.command_id
        data[fields["target_workstation_id"]] = command.target_workstation_id
        data[fields["target_windows_session_id"]] = command.target_windows_session_id
        data[fields["command_type"]] = cls._format_enum(command.command_type)
        data[fields["requested_by_object_id"]] = command.requested_by_object_id
        data[fields["requested_by_upn"]] = command.requested_by_upn
        data[fields["requested_at_utc"]] = cls._format_datetime(command.requested_at_utc)
        data[fields["expires_at_utc"]] = cls._format_datetime(command.expires_at_utc)
        data[fields["reason"]] = command.reason
        data[fields["status"]] = cls._format_enum(command.status)
        data[fields["executed_at_utc"]] = cls._format_datetime(command.executed_at_utc)
        data[fields["result_message"]] = command.result_message
        
        return data
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> AdminCommandSchema:
        """Convert SharePoint list item to AdminCommandSchema."""
        fields = SharePointFieldMappings.ADMIN_COMMAND_FIELDS
        
        def get_field(field_name: str, default: Any = None) -> Any:
            sp_field = fields.get(field_name)
            if sp_field and sp_field in item:
                return item[sp_field]
            return default
        
        return AdminCommandSchema(
            command_id=get_field("command_id", ""),
            target_workstation_id=get_field("target_workstation_id", ""),
            target_windows_session_id=get_field("target_windows_session_id"),
            command_type=cls._parse_enum(
                get_field("command_type"),
                CommandType,
                CommandType.REFRESH_STATUS
            ),
            requested_by_object_id=get_field("requested_by_object_id", ""),
            requested_by_upn=get_field("requested_by_upn", ""),
            requested_at_utc=cls._parse_datetime(get_field("requested_at_utc")) or datetime.utcnow(),
            expires_at_utc=cls._parse_datetime(get_field("expires_at_utc")) or datetime.utcnow(),
            reason=get_field("reason"),
            status=cls._parse_enum(
                get_field("status"),
                CommandStatus,
                CommandStatus.PENDING
            ),
            executed_at_utc=cls._parse_datetime(get_field("executed_at_utc")),
            result_message=get_field("result_message"),
        )


class AccessRuleConverter(SharePointDataConverter):
    """Convert AccessRuleSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, rule: AccessRuleSchema) -> dict:
        """Convert AccessRuleSchema to SharePoint list item."""
        fields = SharePointFieldMappings.ACCESS_RULE_FIELDS
        
        data: dict[str, Any] = {}
        
        data[fields["rule_id"]] = rule.rule_id
        data[fields["entra_user_or_group_id"]] = rule.entra_user_or_group_id
        data[fields["workstation_id"]] = rule.workstation_id
        data[fields["may_connect"]] = rule.may_connect
        data[fields["may_set_calculation_flag"]] = rule.may_set_calculation_flag
        data[fields["valid_from_utc"]] = cls._format_datetime(rule.valid_from_utc)
        data[fields["valid_until_utc"]] = cls._format_datetime(rule.valid_until_utc)
        data[fields["enabled"]] = rule.enabled
        
        return data
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> AccessRuleSchema:
        """Convert SharePoint list item to AccessRuleSchema."""
        fields = SharePointFieldMappings.ACCESS_RULE_FIELDS
        
        def get_field(field_name: str, default: Any = None) -> Any:
            sp_field = fields.get(field_name)
            if sp_field and sp_field in item:
                return item[sp_field]
            return default
        
        return AccessRuleSchema(
            rule_id=get_field("rule_id", ""),
            entra_user_or_group_id=get_field("entra_user_or_group_id", ""),
            workstation_id=get_field("workstation_id"),
            may_connect=get_field("may_connect", True),
            may_set_calculation_flag=get_field("may_set_calculation_flag", False),
            valid_from_utc=cls._parse_datetime(get_field("valid_from_utc")),
            valid_until_utc=cls._parse_datetime(get_field("valid_until_utc")),
            enabled=get_field("enabled", True),
        )


# =============================================================================
# SharePoint Manager
# =============================================================================

class SharePointManager:
    """High-level manager for SharePoint list operations.
    
    This class provides specialized methods for working with the RDP Portal
    SharePoint lists, including automatic ETag handling and data conversion.
    """
    
    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        auth_provider: Optional[EntraAuthProvider] = None,
        config: Optional[SharePointConfig] = None,
    ):
        """Initialize the SharePoint manager.
        
        Args:
            graph_client: Optional GraphClient instance
            auth_provider: Optional Entra ID authentication provider
            config: Optional SharePoint configuration
        """
        self.config = config or SharePointConfig.from_env()
        
        if graph_client:
            self.graph_client = graph_client
        elif auth_provider:
            self.graph_client = GraphClient(auth_provider)
        else:
            self.graph_client = GraphClient()
    
    def _get_site_id(self) -> str:
        """Get the site ID, fetching it from URL if needed."""
        if self.config.site_id:
            return self.config.site_id
        
        if self.config.site_url:
            # Try to get site by URL
            response = self.graph_client.get_site_by_url(self.config.site_url)
            if response.is_success and response.data:
                self.config.site_id = response.data.get("id", "")
                return self.config.site_id
        
        raise GraphAPIError(
            "SharePoint site configuration is required (site_id or site_url)",
            400
        )
    
    # =========================================================================
    # Workstation Operations
    # =========================================================================
    
    def get_all_workstations(self) -> list[WorkstationSchema]:
        """Get all workstations from SharePoint.
        
        Returns:
            List of WorkstationSchema objects
        """
        site_id = self._get_site_id()
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.workstations_list,
            expand=["fields"],
        )
        
        workstations = []
        for item in paginated.value:
            if item.get("fields"):
                try:
                    ws = WorkstationConverter.from_sharepoint(item["fields"])
                    # Set ETag from the item
                    ws.etag = item.get("etag") or item.get("@odata.etag")
                    workstations.append(ws)
                except Exception as e:
                    logger.warning(f"Failed to parse workstation item: {e}")
        
        return workstations
    
    def get_workstation(self, workstation_id: str) -> Optional[WorkstationSchema]:
        """Get a specific workstation by ID.
        
        Args:
            workstation_id: Workstation ID
            
        Returns:
            WorkstationSchema if found, None otherwise
        """
        site_id = self._get_site_id()
        
        # Get items with filter
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.workstations_list,
            filter=f"WorkstationId eq '{workstation_id}'",
            expand=["fields"],
        )
        
        if not paginated.value:
            return None
        
        item = paginated.value[0]
        if not item.get("fields"):
            return None
        
        ws = WorkstationConverter.from_sharepoint(item["fields"])
        ws.etag = item.get("etag") or item.get("@odata.etag")
        return ws
    
    def create_workstation(self, workstation: WorkstationSchema) -> WorkstationSchema:
        """Create a new workstation in SharePoint.
        
        Args:
            workstation: WorkstationSchema to create
            
        Returns:
            Created WorkstationSchema with updated fields
        """
        site_id = self._get_site_id()
        
        data = WorkstationConverter.to_sharepoint(workstation)
        
        response = self.graph_client.create_list_item(
            site_id=site_id,
            list_id=self.config.workstations_list,
            data=data,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to create workstation: {response.status_code}",
                response.status_code,
            )
        
        # Return the created workstation
        if response.data:
            created_ws = WorkstationConverter.from_sharepoint(response.data.get("fields", response.data))
            created_ws.etag = response.data.get("etag") or response.data.get("@odata.etag")
            return created_ws
        
        return workstation
    
    def update_workstation(
        self,
        workstation: WorkstationSchema,
        etag: Optional[str] = None,
    ) -> WorkstationSchema:
        """Update an existing workstation in SharePoint.
        
        Args:
            workstation: WorkstationSchema with updated data
            etag: Optional ETag for concurrency control
            
        Returns:
            Updated WorkstationSchema
            
        Raises:
            GraphAPIError: If update fails (including ETag mismatch)
        """
        site_id = self._get_site_id()
        
        # Find the item ID
        existing = self.get_workstation(workstation.workstation_id)
        if not existing:
            raise GraphNotFoundError(
                f"Workstation {workstation.workstation_id} not found",
                404,
            )
        
        # Get the item ID from the existing item
        # For SharePoint, we need the internal item ID
        item_id = self._find_item_id(workstation.workstation_id, self.config.workstations_list)
        
        if not item_id:
            raise GraphNotFoundError(
                f"Workstation {workstation.workstation_id} not found in SharePoint",
                404,
            )
        
        # Use provided ETag or from existing
        if etag:
            pass
        elif existing.etag:
            etag = existing.etag
        
        data = WorkstationConverter.to_sharepoint(workstation)
        
        response = self.graph_client.update_list_item(
            site_id=site_id,
            list_id=self.config.workstations_list,
            item_id=item_id,
            data=data,
            etag=etag,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to update workstation: {response.status_code}",
                response.status_code,
            )
        
        # Return updated workstation
        if response.data:
            updated_ws = WorkstationConverter.from_sharepoint(response.data.get("fields", response.data))
            updated_ws.etag = response.data.get("etag") or response.data.get("@odata.etag")
            return updated_ws
        
        return workstation
    
    def _find_item_id(self, workstation_id: str, list_name: str) -> Optional[str]:
        """Find the internal SharePoint item ID for a workstation."""
        site_id = self._get_site_id()
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=list_name,
            filter=f"WorkstationId eq '{workstation_id}'",
            select=["id"],
        )
        
        if paginated.value:
            return paginated.value[0].get("id")
        
        return None
    
    def delete_workstation(self, workstation_id: str, etag: Optional[str] = None) -> bool:
        """Delete a workstation from SharePoint.
        
        Args:
            workstation_id: Workstation ID to delete
            etag: Optional ETag for concurrency control
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        site_id = self._get_site_id()
        
        item_id = self._find_item_id(workstation_id, self.config.workstations_list)
        if not item_id:
            return False
        
        response = self.graph_client.delete_list_item(
            site_id=site_id,
            list_id=self.config.workstations_list,
            item_id=item_id,
            etag=etag,
        )
        
        return response.is_success
    
    # =========================================================================
    # Session Event Operations
    # =========================================================================
    
    def get_session_events(
        self,
        workstation_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        limit: Optional[int] = None,
    ) -> list[SessionEventSchema]:
        """Get session events from SharePoint.
        
        Args:
            workstation_id: Optional filter by workstation ID
            event_type: Optional filter by event type
            limit: Optional maximum number of events to return
            
        Returns:
            List of SessionEventSchema objects
        """
        site_id = self._get_site_id()
        
        filter_parts = []
        if workstation_id:
            filter_parts.append(f"WorkstationId eq '{workstation_id}'")
        if event_type:
            filter_parts.append(f"EventType eq '{event_type.value}'")
        
        filter_str = " and ".join(filter_parts) if filter_parts else None
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.sessions_list,
            filter=filter_str,
            expand=["fields"],
            top=limit,
        )
        
        events = []
        for item in paginated.value:
            if item.get("fields"):
                try:
                    event = SessionEventConverter.from_sharepoint(item["fields"])
                    events.append(event)
                except Exception as e:
                    logger.warning(f"Failed to parse session event item: {e}")
        
        return events
    
    def create_session_event(self, event: SessionEventSchema) -> SessionEventSchema:
        """Create a new session event in SharePoint.
        
        Args:
            event: SessionEventSchema to create
            
        Returns:
            Created SessionEventSchema
        """
        site_id = self._get_site_id()
        
        data = SessionEventConverter.to_sharepoint(event)
        
        response = self.graph_client.create_list_item(
            site_id=site_id,
            list_id=self.config.sessions_list,
            data=data,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to create session event: {response.status_code}",
                response.status_code,
            )
        
        if response.data:
            created_event = SessionEventConverter.from_sharepoint(
                response.data.get("fields", response.data)
            )
            return created_event
        
        return event
    
    # =========================================================================
    # Admin Command Operations
    # =========================================================================
    
    def get_admin_commands(
        self,
        workstation_id: Optional[str] = None,
        status: Optional[CommandStatus] = None,
        requested_by: Optional[str] = None,
    ) -> list[AdminCommandSchema]:
        """Get admin commands from SharePoint.
        
        Args:
            workstation_id: Optional filter by target workstation
            status: Optional filter by command status
            requested_by: Optional filter by requester UPN
            
        Returns:
            List of AdminCommandSchema objects
        """
        site_id = self._get_site_id()
        
        filter_parts = []
        if workstation_id:
            filter_parts.append(f"TargetWorkstationId eq '{workstation_id}'")
        if status:
            filter_parts.append(f"Status eq '{status.value}'")
        if requested_by:
            filter_parts.append(f"RequestedByUpn eq '{requested_by}'")
        
        filter_str = " and ".join(filter_parts) if filter_parts else None
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.commands_list,
            filter=filter_str,
            expand=["fields"],
        )
        
        commands = []
        for item in paginated.value:
            if item.get("fields"):
                try:
                    cmd = AdminCommandConverter.from_sharepoint(item["fields"])
                    commands.append(cmd)
                except Exception as e:
                    logger.warning(f"Failed to parse admin command item: {e}")
        
        return commands
    
    def get_admin_command(self, command_id: str) -> Optional[AdminCommandSchema]:
        """Get a specific admin command by ID.
        
        Args:
            command_id: Command ID
            
        Returns:
            AdminCommandSchema if found, None otherwise
        """
        site_id = self._get_site_id()
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.commands_list,
            filter=f"CommandId eq '{command_id}'",
            expand=["fields"],
        )
        
        if not paginated.value:
            return None
        
        item = paginated.value[0]
        if not item.get("fields"):
            return None
        
        cmd = AdminCommandConverter.from_sharepoint(item["fields"])
        return cmd
    
    def create_admin_command(self, command: AdminCommandSchema) -> AdminCommandSchema:
        """Create a new admin command in SharePoint.
        
        Args:
            command: AdminCommandSchema to create
            
        Returns:
            Created AdminCommandSchema
        """
        site_id = self._get_site_id()
        
        data = AdminCommandConverter.to_sharepoint(command)
        
        response = self.graph_client.create_list_item(
            site_id=site_id,
            list_id=self.config.commands_list,
            data=data,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to create admin command: {response.status_code}",
                response.status_code,
            )
        
        if response.data:
            created_cmd = AdminCommandConverter.from_sharepoint(
                response.data.get("fields", response.data)
            )
            return created_cmd
        
        return command
    
    def update_admin_command(
        self,
        command: AdminCommandSchema,
        etag: Optional[str] = None,
    ) -> AdminCommandSchema:
        """Update an existing admin command in SharePoint.
        
        Args:
            command: AdminCommandSchema with updated data
            etag: Optional ETag for concurrency control
            
        Returns:
            Updated AdminCommandSchema
        """
        site_id = self._get_site_id()
        
        item_id = self._find_item_id(command.command_id, self.config.commands_list)
        if not item_id:
            raise GraphNotFoundError(
                f"Admin command {command.command_id} not found",
                404,
            )
        
        data = AdminCommandConverter.to_sharepoint(command)
        
        response = self.graph_client.update_list_item(
            site_id=site_id,
            list_id=self.config.commands_list,
            item_id=item_id,
            data=data,
            etag=etag,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to update admin command: {response.status_code}",
                response.status_code,
            )
        
        if response.data:
            updated_cmd = AdminCommandConverter.from_sharepoint(
                response.data.get("fields", response.data)
            )
            return updated_cmd
        
        return command
    
    def delete_admin_command(self, command_id: str, etag: Optional[str] = None) -> bool:
        """Delete an admin command from SharePoint.
        
        Args:
            command_id: Command ID to delete
            etag: Optional ETag for concurrency control
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        site_id = self._get_site_id()
        
        item_id = self._find_item_id(command_id, self.config.commands_list)
        if not item_id:
            return False
        
        response = self.graph_client.delete_list_item(
            site_id=site_id,
            list_id=self.config.commands_list,
            item_id=item_id,
            etag=etag,
        )
        
        return response.is_success
    
    # =========================================================================
    # Access Rule Operations
    # =========================================================================
    
    def get_access_rules(
        self,
        user_or_group_id: Optional[str] = None,
        workstation_id: Optional[str] = None,
    ) -> list[AccessRuleSchema]:
        """Get access rules from SharePoint.
        
        Args:
            user_or_group_id: Optional filter by user or group ID
            workstation_id: Optional filter by workstation ID
            
        Returns:
            List of AccessRuleSchema objects
        """
        site_id = self._get_site_id()
        
        filter_parts = []
        if user_or_group_id:
            filter_parts.append(f"EntraUserOrGroupId eq '{user_or_group_id}'")
        if workstation_id:
            filter_parts.append(f"WorkstationId eq '{workstation_id}'")
        
        filter_str = " and ".join(filter_parts) if filter_parts else None
        
        paginated = self.graph_client.get_list_items(
            site_id=site_id,
            list_id=self.config.access_rules_list,
            filter=filter_str,
            expand=["fields"],
        )
        
        rules = []
        for item in paginated.value:
            if item.get("fields"):
                try:
                    rule = AccessRuleConverter.from_sharepoint(item["fields"])
                    rules.append(rule)
                except Exception as e:
                    logger.warning(f"Failed to parse access rule item: {e}")
        
        return rules
    
    def create_access_rule(self, rule: AccessRuleSchema) -> AccessRuleSchema:
        """Create a new access rule in SharePoint.
        
        Args:
            rule: AccessRuleSchema to create
            
        Returns:
            Created AccessRuleSchema
        """
        site_id = self._get_site_id()
        
        data = AccessRuleConverter.to_sharepoint(rule)
        
        response = self.graph_client.create_list_item(
            site_id=site_id,
            list_id=self.config.access_rules_list,
            data=data,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to create access rule: {response.status_code}",
                response.status_code,
            )
        
        if response.data:
            created_rule = AccessRuleConverter.from_sharepoint(
                response.data.get("fields", response.data)
            )
            return created_rule
        
        return rule
    
    def update_access_rule(
        self,
        rule: AccessRuleSchema,
        etag: Optional[str] = None,
    ) -> AccessRuleSchema:
        """Update an existing access rule in SharePoint.
        
        Args:
            rule: AccessRuleSchema with updated data
            etag: Optional ETag for concurrency control
            
        Returns:
            Updated AccessRuleSchema
        """
        site_id = self._get_site_id()
        
        item_id = self._find_item_id(rule.rule_id, self.config.access_rules_list)
        if not item_id:
            raise GraphNotFoundError(
                f"Access rule {rule.rule_id} not found",
                404,
            )
        
        data = AccessRuleConverter.to_sharepoint(rule)
        
        response = self.graph_client.update_list_item(
            site_id=site_id,
            list_id=self.config.access_rules_list,
            item_id=item_id,
            data=data,
            etag=etag,
        )
        
        if not response.is_success:
            raise GraphAPIError(
                f"Failed to update access rule: {response.status_code}",
                response.status_code,
            )
        
        if response.data:
            updated_rule = AccessRuleConverter.from_sharepoint(
                response.data.get("fields", response.data)
            )
            return updated_rule
        
        return rule
    
    def delete_access_rule(self, rule_id: str, etag: Optional[str] = None) -> bool:
        """Delete an access rule from SharePoint.
        
        Args:
            rule_id: Rule ID to delete
            etag: Optional ETag for concurrency control
            
        Returns:
            True if deletion succeeded, False otherwise
        """
        site_id = self._get_site_id()
        
        item_id = self._find_item_id(rule_id, self.config.access_rules_list)
        if not item_id:
            return False
        
        response = self.graph_client.delete_list_item(
            site_id=site_id,
            list_id=self.config.access_rules_list,
            item_id=item_id,
            etag=etag,
        )
        
        return response.is_success


# =============================================================================
# Factory and Exports
# =============================================================================

def create_sharepoint_manager(
    graph_client: Optional[GraphClient] = None,
    auth_provider: Optional[EntraAuthProvider] = None,
    config: Optional[SharePointConfig] = None,
) -> SharePointManager:
    """Factory function to create a SharePointManager.
    
    Args:
        graph_client: Optional GraphClient instance
        auth_provider: Optional Entra ID authentication provider
        config: Optional SharePoint configuration
        
    Returns:
        Configured SharePointManager instance
    """
    return SharePointManager(graph_client, auth_provider, config)


__all__ = [
    "SharePointConfig",
    "SharePointFieldMappings",
    "SharePointDataConverter",
    "WorkstationConverter",
    "SessionEventConverter",
    "AdminCommandConverter",
    "AccessRuleConverter",
    "SharePointManager",
    "create_sharepoint_manager",
]
