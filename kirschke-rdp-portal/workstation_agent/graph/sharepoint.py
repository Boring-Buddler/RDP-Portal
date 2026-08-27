"""SharePoint list operations for Kirschke RDP Workstation Agent.

This module provides specialized operations for SharePoint lists used by the
RDP Workstation Agent, with data conversion between SharePoint items and
portal data schemas.

Note: This is a simplified version for the agent that doesn't depend on
portal_app modules to avoid circular imports.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

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
from shared.schemas import (
    WorkstationSchema,
    SessionEventSchema,
    AdminCommandSchema,
    AccessRuleSchema,
    ManualFlagSchema,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Converters
# =============================================================================

class SharePointDataConverter:
    """Base class for SharePoint data conversion."""
    
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
        if hasattr(enum_value, "value"):
            return enum_value.value
        return str(enum_value)
    
    @staticmethod
    def _parse_enum(value: Any, enum_class: type, default: Any) -> Any:
        """Parse enum value from SharePoint."""
        if value is None:
            return default
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
    def from_sharepoint(cls, item: dict) -> WorkstationSchema:
        """Convert SharePoint list item to WorkstationSchema."""
        def get_field(field_name: str, default: Any = None) -> Any:
            field_mapping = {
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
                "manual_flag_flag_type": "ManualFlagType",
                "manual_flag_reason": "ManualFlagReason",
                "manual_flag_project": "ManualFlagProject",
                "manual_flag_set_by_object_id": "ManualFlagSetByObjectId",
                "manual_flag_set_by_upn": "ManualFlagSetByUpn",
                "manual_flag_set_at_utc": "ManualFlagSetAtUtc",
                "manual_flag_expires_at_utc": "ManualFlagExpiresAtUtc",
            }
            
            sp_field = field_mapping.get(field_name)
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
            etag=item.get("etag"),
        )


class SessionEventConverter(SharePointDataConverter):
    """Convert SessionEventSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, event: SessionEventSchema) -> dict:
        """Convert SessionEventSchema to SharePoint list item."""
        return {
            "EventId": event.event_id,
            "TimestampUtc": cls._format_datetime(event.timestamp_utc),
            "EventType": cls._format_enum(event.event_type),
            "WorkstationId": event.workstation_id,
            "WorkstationHostname": event.workstation_hostname,
            "WindowsSessionId": event.windows_session_id,
            "SessionUserUpn": event.session_user_upn,
            "SessionUserDomain": event.session_user_domain,
            "ClientName": event.client_name,
            "ClientIp": event.client_ip,
            "ActorEntraObjectId": event.actor_entra_object_id,
            "ActorUpn": event.actor_upn,
            "Result": cls._format_enum(event.result),
            "Reason": event.reason,
            "Source": cls._format_enum(event.source),
            "CorrelationId": event.correlation_id,
            "AgentVersion": event.agent_version,
        }
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> SessionEventSchema:
        """Convert SharePoint list item to SessionEventSchema."""
        return SessionEventSchema(
            event_id=item.get("EventId", ""),
            timestamp_utc=cls._parse_datetime(item.get("TimestampUtc")) or datetime.now(timezone.utc),
            event_type=cls._parse_enum(item.get("EventType"), EventType, EventType.LAUNCH_REQUESTED),
            workstation_id=item.get("WorkstationId", ""),
            workstation_hostname=item.get("WorkstationHostname"),
            windows_session_id=item.get("WindowsSessionId"),
            session_user_upn=item.get("SessionUserUpn"),
            session_user_domain=item.get("SessionUserDomain"),
            client_name=item.get("ClientName"),
            client_ip=item.get("ClientIp"),
            actor_entra_object_id=item.get("ActorEntraObjectId"),
            actor_upn=item.get("ActorUpn"),
            result=cls._parse_enum(item.get("Result"), EventResult, None),
            reason=item.get("Reason"),
            source=cls._parse_enum(item.get("Source"), EventSource, EventSource.AGENT),
            correlation_id=item.get("CorrelationId"),
            agent_version=item.get("AgentVersion"),
        )


class AdminCommandConverter(SharePointDataConverter):
    """Convert AdminCommandSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, command: AdminCommandSchema) -> dict:
        """Convert AdminCommandSchema to SharePoint list item."""
        return {
            "CommandId": command.command_id,
            "TargetWorkstationId": command.target_workstation_id,
            "TargetWindowsSessionId": command.target_windows_session_id,
            "CommandType": cls._format_enum(command.command_type),
            "RequestedByObjectId": command.requested_by_object_id,
            "RequestedByUpn": command.requested_by_upn,
            "RequestedAtUtc": cls._format_datetime(command.requested_at_utc),
            "ExpiresAtUtc": cls._format_datetime(command.expires_at_utc),
            "Reason": command.reason,
            "Status": cls._format_enum(command.status),
            "ExecutedAtUtc": cls._format_datetime(command.executed_at_utc),
            "ResultMessage": command.result_message,
        }
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> AdminCommandSchema:
        """Convert SharePoint list item to AdminCommandSchema."""
        return AdminCommandSchema(
            command_id=item.get("CommandId", ""),
            target_workstation_id=item.get("TargetWorkstationId", ""),
            target_windows_session_id=item.get("TargetWindowsSessionId"),
            command_type=cls._parse_enum(item.get("CommandType"), CommandType, CommandType.REFRESH_STATUS),
            requested_by_object_id=item.get("RequestedByObjectId", ""),
            requested_by_upn=item.get("RequestedByUpn", ""),
            requested_at_utc=cls._parse_datetime(item.get("RequestedAtUtc")) or datetime.now(timezone.utc),
            expires_at_utc=cls._parse_datetime(item.get("ExpiresAtUtc")) or datetime.now(timezone.utc),
            reason=item.get("Reason"),
            status=cls._parse_enum(item.get("Status"), CommandStatus, CommandStatus.PENDING),
            executed_at_utc=cls._parse_datetime(item.get("ExecutedAtUtc")),
            result_message=item.get("ResultMessage"),
        )


class AccessRuleConverter(SharePointDataConverter):
    """Convert AccessRuleSchema to/from SharePoint list items."""
    
    @classmethod
    def to_sharepoint(cls, rule: AccessRuleSchema) -> dict:
        """Convert AccessRuleSchema to SharePoint list item."""
        return {
            "RuleId": rule.rule_id,
            "EntraUserOrGroupId": rule.entra_user_or_group_id,
            "WorkstationId": rule.workstation_id,
            "MayConnect": rule.may_connect,
            "MaySetCalculationFlag": rule.may_set_calculation_flag,
            "ValidFromUtc": cls._format_datetime(rule.valid_from_utc),
            "ValidUntilUtc": cls._format_datetime(rule.valid_until_utc),
            "Enabled": rule.enabled,
        }
    
    @classmethod
    def from_sharepoint(cls, item: dict) -> AccessRuleSchema:
        """Convert SharePoint list item to AccessRuleSchema."""
        return AccessRuleSchema(
            rule_id=item.get("RuleId", ""),
            entra_user_or_group_id=item.get("EntraUserOrGroupId", ""),
            workstation_id=item.get("WorkstationId"),
            may_connect=item.get("MayConnect", True),
            may_set_calculation_flag=item.get("MaySetCalculationFlag", False),
            valid_from_utc=cls._parse_datetime(item.get("ValidFromUtc")),
            valid_until_utc=cls._parse_datetime(item.get("ValidUntilUtc")),
            enabled=item.get("Enabled", True),
        )


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "SharePointDataConverter",
    "WorkstationConverter",
    "SessionEventConverter",
    "AdminCommandConverter",
    "AccessRuleConverter",
]
