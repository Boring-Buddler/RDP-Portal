"""Pydantic schemas for Kirschke RDP Workstation Portal.

These schemas define the data structures used for communication between
the portal application, workstation agent, and SharePoint lists.
"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from shared.enums import (
    AgentStatus,
    ManualFlagType,
    SessionState,
    EventType,
    EventResult,
    EventSource,
    CommandType,
    CommandStatus,
)


# =============================================================================
# Base Schemas
# =============================================================================

class BaseSchema(BaseModel):
    """Base schema with common configuration."""
    
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None,
        },
    )


# =============================================================================
# Manual Flag Schema
# =============================================================================

class ManualFlagSchema(BaseSchema):
    """Manual flag information."""
    
    flag_type: ManualFlagType = Field(
        default=ManualFlagType.NONE,
        description="Type of the manual flag"
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reason for setting the flag"
    )
    project: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional project or task reference"
    )
    set_by_object_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Entra ID object ID of the user who set the flag"
    )
    set_by_upn: Optional[str] = Field(
        default=None,
        max_length=256,
        description="UPN of the user who set the flag"
    )
    set_at_utc: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the flag was set (UTC)"
    )
    expires_at_utc: Optional[datetime] = Field(
        default=None,
        description="Optional expiration timestamp (UTC)"
    )
    
    @field_validator("flag_type", mode="before")
    @classmethod
    def validate_flag_type(cls, v: Any) -> ManualFlagType:
        if isinstance(v, str):
            try:
                return ManualFlagType(v)
            except ValueError:
                return ManualFlagType.NONE
        return v


# =============================================================================
# RDP Profile Schema
# =============================================================================

class RDPProfileSchema(BaseSchema):
    """RDP connection profile settings."""
    
    hostname: str = Field(
        ...,
        max_length=256,
        description="Hostname or FQDN of the workstation"
    )
    fqdn: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Fully qualified domain name"
    )
    display_name: str = Field(
        ...,
        max_length=100,
        description="Display name for the workstation"
    )
    site: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Location or site"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional description"
    )
    username_hint: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Username hint (UPN or username)"
    )
    entra_sso_enabled: bool = Field(
        default=False,
        description="Whether Entra SSO is enabled"
    )
    gateway_hostname: Optional[str] = Field(
        default=None,
        max_length=256,
        description="RD Gateway hostname"
    )
    use_all_monitors: bool = Field(
        default=False,
        description="Use all monitors"
    )
    redirect_clipboard: bool = Field(
        default=True,
        description="Redirect clipboard"
    )
    redirect_drives: bool = Field(
        default=False,
        description="Redirect local drives"
    )
    redirect_printers: bool = Field(
        default=False,
        description="Redirect printers"
    )
    redirect_audio: bool = Field(
        default=False,
        description="Redirect audio"
    )
    screen_mode: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Screen mode (e.g., fullscreen, windowed)"
    )
    resolution: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Screen resolution"
    )
    enabled: bool = Field(
        default=True,
        description="Whether the workstation is enabled"
    )
    allowed_entra_group_ids: list[str] = Field(
        default_factory=list,
        description="List of allowed Entra group IDs"
    )


# =============================================================================
# Session Event Schema
# =============================================================================

class SessionEventSchema(BaseSchema):
    """Schema for session events stored in SharePoint."""
    
    event_id: str = Field(
        ...,
        max_length=100,
        description="Unique event identifier"
    )
    timestamp_utc: datetime = Field(
        ...,
        description="Event timestamp in UTC"
    )
    event_type: EventType = Field(
        ...,
        description="Type of the event"
    )
    workstation_id: str = Field(
        ...,
        max_length=100,
        description="ID of the workstation"
    )
    workstation_hostname: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Hostname of the workstation"
    )
    windows_session_id: Optional[int] = Field(
        default=None,
        ge=0,
        description="Windows session ID"
    )
    session_user_upn: Optional[str] = Field(
        default=None,
        max_length=256,
        description="UPN of the session user"
    )
    session_user_domain: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Domain of the session user"
    )
    client_name: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Name of the client machine"
    )
    client_ip: Optional[str] = Field(
        default=None,
        max_length=50,
        description="IP address of the client"
    )
    actor_entra_object_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Entra object ID of the actor"
    )
    actor_upn: Optional[str] = Field(
        default=None,
        max_length=256,
        description="UPN of the actor"
    )
    result: Optional[EventResult] = Field(
        default=None,
        description="Result of the event"
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reason or additional information"
    )
    source: EventSource = Field(
        default=EventSource.PORTAL,
        description="Source of the event"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Correlation ID for tracking related events"
    )
    agent_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Version of the agent"
    )


# =============================================================================
# Admin Command Schema
# =============================================================================

class AdminCommandSchema(BaseSchema):
    """Schema for admin commands."""
    
    command_id: str = Field(
        ...,
        max_length=100,
        description="Unique command identifier"
    )
    target_workstation_id: str = Field(
        ...,
        max_length=100,
        description="ID of the target workstation"
    )
    target_windows_session_id: Optional[int] = Field(
        default=None,
        ge=0,
        description="Target Windows session ID"
    )
    command_type: CommandType = Field(
        ...,
        description="Type of the command"
    )
    requested_by_object_id: str = Field(
        ...,
        max_length=100,
        description="Entra object ID of the requester"
    )
    requested_by_upn: str = Field(
        ...,
        max_length=256,
        description="UPN of the requester"
    )
    requested_at_utc: datetime = Field(
        ...,
        description="Request timestamp in UTC"
    )
    expires_at_utc: datetime = Field(
        ...,
        description="Expiration timestamp in UTC"
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Reason for the command"
    )
    status: CommandStatus = Field(
        default=CommandStatus.PENDING,
        description="Current status of the command"
    )
    executed_at_utc: Optional[datetime] = Field(
        default=None,
        description="Execution timestamp in UTC"
    )
    result_message: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Result message"
    )


# =============================================================================
# Access Rule Schema
# =============================================================================

class AccessRuleSchema(BaseSchema):
    """Schema for access rules."""
    
    rule_id: str = Field(
        ...,
        max_length=100,
        description="Unique rule identifier"
    )
    entra_user_or_group_id: str = Field(
        ...,
        max_length=100,
        description="Entra user or group ID"
    )
    workstation_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Target workstation ID (null for all)"
    )
    may_connect: bool = Field(
        default=True,
        description="Whether connection is allowed"
    )
    may_set_calculation_flag: bool = Field(
        default=False,
        description="Whether user may set calculation flag"
    )
    valid_from_utc: Optional[datetime] = Field(
        default=None,
        description="Valid from timestamp"
    )
    valid_until_utc: Optional[datetime] = Field(
        default=None,
        description="Valid until timestamp"
    )
    enabled: bool = Field(
        default=True,
        description="Whether the rule is enabled"
    )


# =============================================================================
# Workstation Schema (Complete)
# =============================================================================

class WorkstationSchema(BaseSchema):
    """Complete schema for a workstation including all metadata."""
    
    workstation_id: str = Field(
        ...,
        max_length=100,
        description="Unique workstation identifier"
    )
    display_name: str = Field(
        ...,
        max_length=100,
        description="Display name"
    )
    hostname: str = Field(
        ...,
        max_length=256,
        description="Hostname"
    )
    fqdn: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Fully qualified domain name"
    )
    site: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Location or site"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Description"
    )
    enabled: bool = Field(
        default=True,
        description="Whether enabled"
    )
    allowed_entra_group_ids: list[str] = Field(
        default_factory=list,
        description="Allowed Entra group IDs"
    )
    username_hint: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Username hint"
    )
    entra_sso_enabled: bool = Field(
        default=False,
        description="Entra SSO enabled"
    )
    gateway_hostname: Optional[str] = Field(
        default=None,
        max_length=256,
        description="RD Gateway hostname"
    )
    use_all_monitors: bool = Field(
        default=False,
        description="Use all monitors"
    )
    redirect_clipboard: bool = Field(
        default=True,
        description="Redirect clipboard"
    )
    redirect_drives: bool = Field(
        default=False,
        description="Redirect drives"
    )
    redirect_printers: bool = Field(
        default=False,
        description="Redirect printers"
    )
    redirect_audio: bool = Field(
        default=False,
        description="Redirect audio"
    )
    screen_mode: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Screen mode"
    )
    resolution: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Resolution"
    )
    
    # Manual flag
    manual_flag: ManualFlagSchema = Field(
        default_factory=ManualFlagSchema,
        description="Manual flag information"
    )
    
    # Agent status
    agent_status: AgentStatus = Field(
        default=AgentStatus.OFFLINE,
        description="Agent status"
    )
    agent_last_seen_utc: Optional[datetime] = Field(
        default=None,
        description="Last seen timestamp"
    )
    agent_version: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Agent version"
    )
    
    # Current session
    current_session_state: SessionState = Field(
        default=SessionState.NONE,
        description="Current session state"
    )
    current_session_user: Optional[str] = Field(
        default=None,
        max_length=256,
        description="Current session user"
    )
    current_windows_session_id: Optional[int] = Field(
        default=None,
        ge=0,
        description="Current Windows session ID"
    )
    last_session_event_utc: Optional[datetime] = Field(
        default=None,
        description="Last session event timestamp"
    )
    
    # SharePoint metadata
    etag: Optional[str] = Field(
        default=None,
        description="ETag for concurrency control"
    )
    
    def get_rdp_profile(self) -> RDPProfileSchema:
        """Extract RDP profile from workstation data."""
        return RDPProfileSchema(
            hostname=self.hostname,
            fqdn=self.fqdn,
            display_name=self.display_name,
            site=self.site,
            description=self.description,
            username_hint=self.username_hint,
            entra_sso_enabled=self.entra_sso_enabled,
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
    
    def is_blocked(self) -> bool:
        """Check if workstation is blocked by a manual flag."""
        return self.manual_flag.flag_type in [
            ManualFlagType.BLOCKED,
            ManualFlagType.MAINTENANCE,
            ManualFlagType.CALCULATION_RUNNING,
        ]
    
    def can_disconnect(self) -> bool:
        """Check if disconnect is allowed (always for calculation_running)."""
        if self.manual_flag.flag_type == ManualFlagType.CALCULATION_RUNNING:
            return True
        return not self.is_blocked()
    
    def can_logoff(self) -> bool:
        """Check if logoff is allowed (blocked for all flags)."""
        return not self.is_blocked()


__all__ = [
    "BaseSchema",
    "ManualFlagSchema",
    "RDPProfileSchema",
    "SessionEventSchema",
    "AdminCommandSchema",
    "AccessRuleSchema",
    "WorkstationSchema",
]
