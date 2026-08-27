"""Microsoft Graph API client for Kirschke RDP Workstation Agent.

This module provides a Graph API client for the agent to communicate with
SharePoint and Microsoft Graph using application-only authentication with
certificate-based auth.

Features:
- Certificate-based authentication (app-only)
- Token acquisition and caching
- Workstation status updates
- Session event submission
- Admin command fetching
- Access rule checking
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from pathlib import Path
from threading import Lock

import msal
from msal import ConfidentialClientApplication

from shared.schemas import (
    WorkstationSchema,
    SessionEventSchema,
    AdminCommandSchema,
    AccessRuleSchema,
)
from shared.enums import AgentStatus, SessionState

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class AgentGraphConfig:
    """Configuration for agent Graph API client."""
    
    # Tenant ID
    tenant_id: str = os.getenv("TENANT_ID", "")
    
    # Agent client ID
    client_id: str = os.getenv("AGENT_CLIENT_ID", "")
    
    # Authority URL
    authority: str = os.getenv("AUTHORITY", "")
    
    # Certificate thumbprint
    certificate_thumbprint: str = os.getenv("AGENT_CERT_THUMBPRINT", "")
    
    # Certificate store name
    certificate_store: str = os.getenv("AGENT_CERT_STORE", "My")
    
    # Scopes
    scopes: list[str] = field(default_factory=lambda: [
        "https://graph.microsoft.com/.default",
    ])
    
    # SharePoint site ID
    sharepoint_site_id: str = os.getenv("SHAREPOINT_SITE_ID", "")
    
    # SharePoint list names
    workstations_list: str = os.getenv("SHAREPOINT_WORKSTATIONS_LIST", "RDP_Workstations")
    sessions_list: str = os.getenv("SHAREPOINT_SESSIONS_LIST", "RDP_SessionEvents")
    commands_list: str = os.getenv("SHAREPOINT_COMMANDS_LIST", "RDP_AdminCommands")
    access_rules_list: str = os.getenv("SHAREPOINT_ACCESS_RULES_LIST", "RDP_AccessRules")
    
    # Token cache path
    token_cache_path: str = os.getenv("AGENT_TOKEN_CACHE_PATH", "")
    
    @classmethod
    def from_env(cls) -> "AgentGraphConfig":
        """Create configuration from environment variables."""
        # Build authority if not set
        authority = os.getenv("AUTHORITY", "")
        if not authority and os.getenv("TENANT_ID"):
            authority = f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}"
        
        # Set cache path if not set
        cache_path = os.getenv("AGENT_TOKEN_CACHE_PATH", "")
        if not cache_path:
            cache_dir = Path.home() / ".kirschke" / "rdp-agent" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = str(cache_dir / "graph_cache.json")
        
        return cls(
            tenant_id=os.getenv("TENANT_ID", ""),
            client_id=os.getenv("AGENT_CLIENT_ID", ""),
            authority=authority,
            certificate_thumbprint=os.getenv("AGENT_CERT_THUMBPRINT", ""),
            certificate_store=os.getenv("AGENT_CERT_STORE", "My"),
            sharepoint_site_id=os.getenv("SHAREPOINT_SITE_ID", ""),
            token_cache_path=cache_path,
        )
    
    def validate(self) -> bool:
        """Validate configuration."""
        required = [self.tenant_id, self.client_id, self.certificate_thumbprint]
        return all(required)


# =============================================================================
# Token Cache
# =============================================================================

class AgentTokenCache:
    """Token cache for agent authentication."""
    
    def __init__(self, cache_path: str):
        """Initialize the token cache.
        
        Args:
            cache_path: Path to cache file
        """
        self.cache_path = cache_path
        self._cache: dict = {}
        self._lock = Lock()
        self._load()
    
    def _load(self) -> None:
        """Load cache from file."""
        try:
            if Path(self.cache_path).exists():
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load agent token cache: {e}")
            self._cache = {}
    
    def _save(self) -> None:
        """Save cache to file."""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save agent token cache: {e}")
    
    def get(self) -> dict:
        """Get cache dictionary."""
        with self._lock:
            return self._cache.copy()
    
    def set(self, cache: dict) -> None:
        """Set cache dictionary."""
        with self._lock:
            self._cache = cache.copy()
            self._save()
    
    def clear(self) -> None:
        """Clear cache."""
        with self._lock:
            self._cache = {}
            self._save()


# =============================================================================
# Certificate Helper
# =============================================================================

class CertificateHelper:
    """Helper for working with Windows certificates."""
    
    @staticmethod
    def get_certificate_by_thumbprint(
        thumbprint: str,
        store_name: str = "My",
    ) -> Optional[Any]:
        """Get a certificate by thumbprint from Windows certificate store.
        
        Args:
            thumbprint: Certificate thumbprint (hex string, no spaces)
            store_name: Certificate store name (e.g., "My", "Root", "CA")
            
        Returns:
            Certificate object or None if not found
        """
        try:
            import win32crypt
            import win32con
            
            # Open certificate store
            store = win32crypt.CertOpenSystemStoreA(None, store_name.encode())
            
            if not store:
                logger.error(f"Failed to open certificate store: {store_name}")
                return None
            
            # Iterate through certificates
            cert = win32crypt.CertEnumCertificatesInStore(store)
            while cert:
                # Get certificate hash (thumbprint)
                cert_hash = win32crypt.CertGetCertificateContextProperty(
                    cert,
                    win32con.CERT_HASH_PROP_ID
                )
                
                if cert_hash:
                    # Format as hex string
                    formatted_hash = "".join(f"{b:02x}" for b in cert_hash).upper()
                    if formatted_hash.replace(":", "").replace(" ", "") == thumbprint.replace(":", "").replace(" ", ""):
                        return cert
                
                cert = win32crypt.CertEnumCertificatesInStore(store, cert)
            
            win32crypt.CertCloseStore(store, 0)
            
        except Exception as e:
            logger.error(f"Failed to get certificate by thumbprint: {e}")
        
        return None
    
    @staticmethod
    def get_certificate_private_key(cert) -> Optional[Any]:
        """Get private key from a certificate.
        
        Args:
            cert: Certificate object
            
        Returns:
            Private key object or None
        """
        try:
            import win32crypt
            import win32con
            
            # Try to get private key
            key_spec = win32crypt.CertGetCertificateContextProperty(
                cert,
                win32con.CERT_KEY_SPEC_PROP_ID
            )
            
            if key_spec == win32con.AT_KEYEXCHANGE:
                return cert
            elif key_spec == win32con.AT_SIGNATURE:
                return cert
            
        except Exception as e:
            logger.error(f"Failed to get private key: {e}")
        
        return None


# =============================================================================
# Agent Graph Client
# =============================================================================

class AgentGraphClient:
    """Microsoft Graph API client for the workstation agent.
    
    This client uses certificate-based authentication to communicate with
    Microsoft Graph API on behalf of the agent application.
    
    Example usage:
        client = AgentGraphClient()
        if client.authenticate():
            workstations = client.get_workstations()
    """
    
    def __init__(self, config: Optional[AgentGraphConfig] = None):
        """Initialize the agent Graph client.
        
        Args:
            config: Optional configuration
        """
        self.config = config or AgentGraphConfig.from_env()
        self._app: Optional[ConfidentialClientApplication] = None
        self._cache: Optional[AgentTokenCache] = None
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """Initialize the Graph client.
        
        Returns:
            True if initialization succeeded
        """
        if not self.config.validate():
            logger.error("Agent Graph configuration is incomplete")
            return False
        
        try:
            # Create token cache
            self._cache = AgentTokenCache(self.config.token_cache_path)
            
            # Create MSAL confidential client
            self._app = ConfidentialClientApplication(
                client_id=self.config.client_id,
                authority=self.config.authority,
                client_credential=self._get_client_credential(),
            )
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize agent Graph client: {e}")
            return False
    
    def _get_client_credential(self) -> Any:
        """Get client credential (certificate) for authentication."""
        try:
            # Get certificate by thumbprint
            cert = CertificateHelper.get_certificate_by_thumbprint(
                self.config.certificate_thumbprint,
                self.config.certificate_store,
            )
            
            if not cert:
                raise RuntimeError(
                    f"Certificate with thumbprint {self.config.certificate_thumbprint} "
                    f"not found in store {self.config.certificate_store}"
                )
            
            # Create credential from certificate
            from msal import SigningKey
            return {
                "private_key": cert,
                "thumbprint": self.config.certificate_thumbprint,
            }
            
        except Exception as e:
            logger.error(f"Failed to get client credential: {e}")
            raise
    
    def is_authenticated(self) -> bool:
        """Check if the client is authenticated.
        
        Returns:
            True if authenticated
        """
        if not self._initialized:
            return False
        
        if self._access_token and self._token_expires:
            return datetime.now(timezone.utc) < self._token_expires
        
        return False
    
    def authenticate(self) -> bool:
        """Authenticate with Microsoft Graph.
        
        Returns:
            True if authentication succeeded
        """
        if not self._initialized:
            if not self.initialize():
                return False
        
        try:
            # Try to get token silently first
            result = self._app.acquire_token_silent(
                scopes=self.config.scopes,
                account=None,
            )
            
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                expires_in = result.get("expires_in", 3600)
                self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                return True
            
            # Try to acquire token for client
            result = self._app.acquire_token_for_client(
                scopes=self.config.scopes,
            )
            
            if result and "access_token" in result:
                self._access_token = result["access_token"]
                expires_in = result.get("expires_in", 3600)
                self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                return True
            
            logger.error(f"Authentication failed: {result.get('error_description', 'Unknown error')}")
            return False
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False
    
    def get_access_token(self) -> Optional[str]:
        """Get the current access token.
        
        Returns:
            Access token if authenticated, None otherwise
        """
        if not self.is_authenticated():
            if not self.authenticate():
                return None
        
        return self._access_token
    
    def refresh_token(self) -> bool:
        """Refresh the access token.
        
        Returns:
            True if token was refreshed
        """
        # Force token refresh
        self._access_token = None
        self._token_expires = None
        return self.authenticate()
    
    def _make_request(
        self,
        method: str,
        url: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Optional[dict]:
        """Make an HTTP request to Graph API.
        
        Args:
            method: HTTP method (GET, POST, PATCH, PUT, DELETE)
            url: Request URL
            data: Request body
            params: Query parameters
            headers: Additional headers
            
        Returns:
            Response data as dictionary, or None on failure
        """
        import requests
        
        token = self.get_access_token()
        if not token:
            logger.error("No access token available")
            return None
        
        # Build full URL
        if not url.startswith("http"):
            url = f"https://graph.microsoft.com/v1.0{url}"
        
        # Build headers
        request_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        if headers:
            request_headers.update(headers)
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                headers=request_headers,
                timeout=30,
            )
            
            if response.status_code >= 400:
                logger.error(
                    f"Graph API request failed: {response.status_code} - {response.text}"
                )
                return None
            
            if response.content:
                return response.json()
            
            return {}
            
        except Exception as e:
            logger.error(f"Graph API request failed: {e}")
            return None
    
    # =========================================================================
    # Workstation Operations
    # =========================================================================
    
    def get_workstation(self, workstation_id: str) -> Optional[WorkstationSchema]:
        """Get workstation information from SharePoint.
        
        Args:
            workstation_id: Workstation ID
            
        Returns:
            WorkstationSchema if found, None otherwise
        """
        if not self.config.sharepoint_site_id:
            logger.error("SharePoint site ID not configured")
            return None
        
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.workstations_list}/items"
        params = {
            "$filter": f"WorkstationId eq '{workstation_id}'",
            "$expand": "fields",
            "$top": 1,
        }
        
        result = self._make_request("GET", url, params=params)
        if not result:
            return None
        
        # Parse the result
        items = result.get("value", [])
        if not items:
            return None
        
        # Convert to WorkstationSchema
        from workstation_agent.graph.sharepoint import WorkstationConverter
        return WorkstationConverter.from_sharepoint(items[0].get("fields", {}))
    
    def update_workstation_status(
        self,
        workstation_id: str,
        agent_status: AgentStatus,
        current_session_state: SessionState,
        current_session_user: Optional[str] = None,
        current_windows_session_id: Optional[int] = None,
        agent_version: Optional[str] = None,
        etag: Optional[str] = None,
    ) -> bool:
        """Update workstation status in SharePoint.
        
        Args:
            workstation_id: Workstation ID
            agent_status: Current agent status
            current_session_state: Current session state
            current_session_user: Current session user UPN
            current_windows_session_id: Current Windows session ID
            agent_version: Agent version
            etag: ETag for concurrency control
            
        Returns:
            True if update succeeded
        """
        if not self.config.sharepoint_site_id:
            logger.error("SharePoint site ID not configured")
            return False
        
        # First, find the item ID
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.workstations_list}/items"
        params = {
            "$filter": f"WorkstationId eq '{workstation_id}'",
            "$select": "id,etag",
            "$top": 1,
        }
        
        result = self._make_request("GET", url, params=params)
        if not result:
            return False
        
        items = result.get("value", [])
        if not items:
            return False
        
        item_id = items[0].get("id")
        item_etag = items[0].get("etag") or etag
        
        if not item_id:
            return False
        
        # Update the item
        update_url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.workstations_list}/items/{item_id}"
        
        data = {
            "AgentStatus": agent_status.value,
            "CurrentSessionState": current_session_state.value,
            "CurrentSessionUser": current_session_user,
            "CurrentWindowsSessionId": current_windows_session_id,
            "AgentLastSeenUtc": datetime.now(timezone.utc).isoformat(),
        }
        
        if agent_version:
            data["AgentVersion"] = agent_version
        
        headers = {}
        if item_etag:
            headers["If-Match"] = item_etag
        
        result = self._make_request("PATCH", update_url, data=data, headers=headers)
        return result is not None
    
    def get_access_rules(self, workstation_id: str) -> list[AccessRuleSchema]:
        """Get access rules for a workstation.
        
        Args:
            workstation_id: Workstation ID
            
        Returns:
            List of AccessRuleSchema objects
        """
        if not self.config.sharepoint_site_id:
            return []
        
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.access_rules_list}/items"
        params = {
            "$filter": f"WorkstationId eq '{workstation_id}' or WorkstationId eq null",
            "$expand": "fields",
        }
        
        result = self._make_request("GET", url, params=params)
        if not result:
            return []
        
        rules = []
        from workstation_agent.graph.sharepoint import AccessRuleConverter
        
        for item in result.get("value", []):
            if item.get("fields"):
                try:
                    rule = AccessRuleConverter.from_sharepoint(item["fields"])
                    rules.append(rule)
                except Exception as e:
                    logger.warning(f"Failed to parse access rule: {e}")
        
        return rules
    
    # =========================================================================
    # Session Event Operations
    # =========================================================================
    
    def create_session_event(self, event: SessionEventSchema) -> bool:
        """Create a session event in SharePoint.
        
        Args:
            event: Session event to create
            
        Returns:
            True if creation succeeded
        """
        if not self.config.sharepoint_site_id:
            logger.error("SharePoint site ID not configured")
            return False
        
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.sessions_list}/items"
        
        from workstation_agent.graph.sharepoint import SessionEventConverter
        data = SessionEventConverter.to_sharepoint(event)
        
        result = self._make_request("POST", url, data=data)
        return result is not None
    
    def create_session_events(self, events: list[SessionEventSchema]) -> int:
        """Create multiple session events in SharePoint.
        
        Args:
            events: List of session events to create
            
        Returns:
            Number of events successfully created
        """
        if not self.config.sharepoint_site_id:
            return 0
        
        from workstation_agent.graph.sharepoint import SessionEventConverter
        
        count = 0
        for event in events:
            if self.create_session_event(event):
                count += 1
        
        return count
    
    # =========================================================================
    # Admin Command Operations
    # =========================================================================
    
    def get_pending_commands(self, workstation_id: str) -> list[AdminCommandSchema]:
        """Get pending admin commands for a workstation.
        
        Args:
            workstation_id: Workstation ID
            
        Returns:
            List of AdminCommandSchema objects
        """
        if not self.config.sharepoint_site_id:
            return []
        
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.commands_list}/items"
        params = {
            "$filter": f"TargetWorkstationId eq '{workstation_id}' and Status eq 'pending'",
            "$expand": "fields",
        }
        
        result = self._make_request("GET", url, params=params)
        if not result:
            return []
        
        commands = []
        from workstation_agent.graph.sharepoint import AdminCommandConverter
        
        for item in result.get("value", []):
            if item.get("fields"):
                try:
                    cmd = AdminCommandConverter.from_sharepoint(item["fields"])
                    commands.append(cmd)
                except Exception as e:
                    logger.warning(f"Failed to parse admin command: {e}")
        
        return commands
    
    def update_command_status(
        self,
        command: AdminCommandSchema,
        status: str,
        result_message: Optional[str] = None,
        etag: Optional[str] = None,
    ) -> bool:
        """Update the status of an admin command.
        
        Args:
            command: Command to update
            status: New status value
            result_message: Optional result message
            etag: Optional ETag for concurrency control
            
        Returns:
            True if update succeeded
        """
        if not self.config.sharepoint_site_id:
            return False
        
        # Find the command item
        url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.commands_list}/items"
        params = {
            "$filter": f"CommandId eq '{command.command_id}'",
            "$select": "id,etag",
            "$top": 1,
        }
        
        result = self._make_request("GET", url, params=params)
        if not result:
            return False
        
        items = result.get("value", [])
        if not items:
            return False
        
        item_id = items[0].get("id")
        item_etag = items[0].get("etag") or etag
        
        if not item_id:
            return False
        
        # Update the command
        update_url = f"/sites/{self.config.sharepoint_site_id}/lists/{self.config.commands_list}/items/{item_id}"
        
        from shared.enums import CommandStatus
        data = {
            "Status": status,
            "ExecutedAtUtc": datetime.now(timezone.utc).isoformat(),
        }
        
        if result_message:
            data["ResultMessage"] = result_message
        
        headers = {}
        if item_etag:
            headers["If-Match"] = item_etag
        
        result = self._make_request("PATCH", update_url, data=data, headers=headers)
        return result is not None


# =============================================================================
# Agent SharePoint Helper (for data conversion)
# =============================================================================

# Import sharepoint converters - we'll create a local version
# to avoid circular imports

class WorkstationConverter:
    """Convert WorkstationSchema to/from SharePoint list items."""
    
    @staticmethod
    def _format_enum(value) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, Enum):
            return value.value
        return str(value)
    
    @staticmethod
    def _parse_enum(value, enum_class, default) -> Enum:
        if value is None:
            return default
        try:
            return enum_class(value)
        except (ValueError, KeyError):
            return default
    
    @staticmethod
    def from_sharepoint(item: dict) -> WorkstationSchema:
        """Convert SharePoint list item to WorkstationSchema."""
        from shared.schemas import ManualFlagSchema
        
        def get_field(field_name: str, default=None) -> Any:
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
                "etag": "ETag",
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
            flag_type=WorkstationConverter._parse_enum(
                get_field("manual_flag_flag_type"),
                ManualFlagType,
                ManualFlagType.NONE
            ),
            reason=get_field("manual_flag_reason"),
            project=get_field("manual_flag_project"),
            set_by_object_id=get_field("manual_flag_set_by_object_id"),
            set_by_upn=get_field("manual_flag_set_by_upn"),
            set_at_utc=self._parse_datetime(get_field("manual_flag_set_at_utc")),
            expires_at_utc=self._parse_datetime(get_field("manual_flag_expires_at_utc")),
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
            allowed_entra_group_ids=self._parse_list(get_field("allowed_entra_group_ids", [])),
            agent_status=WorkstationConverter._parse_enum(
                get_field("agent_status"),
                AgentStatus,
                AgentStatus.OFFLINE
            ),
            agent_last_seen_utc=self._parse_datetime(get_field("agent_last_seen_utc")),
            agent_version=get_field("agent_version"),
            current_session_state=WorkstationConverter._parse_enum(
                get_field("current_session_state"),
                SessionState,
                SessionState.NONE
            ),
            current_session_user=get_field("current_session_user"),
            current_windows_session_id=get_field("current_windows_session_id"),
            last_session_event_utc=self._parse_datetime(get_field("last_session_event_utc")),
            manual_flag=manual_flag,
            etag=item.get("etag"),
        )
    
    @staticmethod
    def _parse_datetime(value) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                return None
        return None
    
    @staticmethod
    def _parse_list(value) -> list:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            import json
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return []


class SessionEventConverter:
    """Convert SessionEventSchema to/from SharePoint."""
    
    @staticmethod
    def to_sharepoint(event: SessionEventSchema) -> dict:
        """Convert SessionEventSchema to SharePoint list item."""
        return {
            "EventId": event.event_id,
            "TimestampUtc": event.timestamp_utc.isoformat(),
            "EventType": event.event_type.value,
            "WorkstationId": event.workstation_id,
            "WorkstationHostname": event.workstation_hostname,
            "WindowsSessionId": event.windows_session_id,
            "SessionUserUpn": event.session_user_upn,
            "SessionUserDomain": event.session_user_domain,
            "ClientName": event.client_name,
            "ClientIp": event.client_ip,
            "ActorEntraObjectId": event.actor_entra_object_id,
            "ActorUpn": event.actor_upn,
            "Result": event.result.value if event.result else None,
            "Reason": event.reason,
            "Source": event.source.value,
            "CorrelationId": event.correlation_id,
            "AgentVersion": event.agent_version,
        }
    
    @staticmethod
    def from_sharepoint(item: dict) -> SessionEventSchema:
        """Convert SharePoint list item to SessionEventSchema."""
        return SessionEventSchema(
            event_id=item.get("EventId", ""),
            timestamp_utc=datetime.fromisoformat(
                item.get("TimestampUtc", datetime.now(timezone.utc).isoformat())
            ),
            event_type=EventType(item.get("EventType", "launch_requested")),
            workstation_id=item.get("WorkstationId", ""),
            workstation_hostname=item.get("WorkstationHostname"),
            windows_session_id=item.get("WindowsSessionId"),
            session_user_upn=item.get("SessionUserUpn"),
            session_user_domain=item.get("SessionUserDomain"),
            client_name=item.get("ClientName"),
            client_ip=item.get("ClientIp"),
            actor_entra_object_id=item.get("ActorEntraObjectId"),
            actor_upn=item.get("ActorUpn"),
            result=EventResult(item.get("Result", "pending")) if item.get("Result") else None,
            reason=item.get("Reason"),
            source=EventSource(item.get("Source", "agent")),
            correlation_id=item.get("CorrelationId"),
            agent_version=item.get("AgentVersion"),
        )


class AdminCommandConverter:
    """Convert AdminCommandSchema to/from SharePoint."""
    
    @staticmethod
    def from_sharepoint(item: dict) -> AdminCommandSchema:
        """Convert SharePoint list item to AdminCommandSchema."""
        from shared.enums import CommandType, CommandStatus
        
        return AdminCommandSchema(
            command_id=item.get("CommandId", ""),
            target_workstation_id=item.get("TargetWorkstationId", ""),
            target_windows_session_id=item.get("TargetWindowsSessionId"),
            command_type=CommandType(item.get("CommandType", "refresh_status")),
            requested_by_object_id=item.get("RequestedByObjectId", ""),
            requested_by_upn=item.get("RequestedByUpn", ""),
            requested_at_utc=datetime.fromisoformat(
                item.get("RequestedAtUtc", datetime.now(timezone.utc).isoformat())
            ),
            expires_at_utc=datetime.fromisoformat(
                item.get("ExpiresAtUtc", datetime.now(timezone.utc).isoformat())
            ),
            reason=item.get("Reason"),
            status=CommandStatus(item.get("Status", "pending")),
            executed_at_utc=datetime.fromisoformat(item.get("ExecutedAtUtc")) 
                if item.get("ExecutedAtUtc") else None,
            result_message=item.get("ResultMessage"),
        )


class AccessRuleConverter:
    """Convert AccessRuleSchema to/from SharePoint."""
    
    @staticmethod
    def from_sharepoint(item: dict) -> AccessRuleSchema:
        """Convert SharePoint list item to AccessRuleSchema."""
        return AccessRuleSchema(
            rule_id=item.get("RuleId", ""),
            entra_user_or_group_id=item.get("EntraUserOrGroupId", ""),
            workstation_id=item.get("WorkstationId"),
            may_connect=item.get("MayConnect", True),
            may_set_calculation_flag=item.get("MaySetCalculationFlag", False),
            valid_from_utc=datetime.fromisoformat(item.get("ValidFromUtc")) 
                if item.get("ValidFromUtc") else None,
            valid_until_utc=datetime.fromisoformat(item.get("ValidUntilUtc")) 
                if item.get("ValidUntilUtc") else None,
            enabled=item.get("Enabled", True),
        )


# =============================================================================
# Factory and Exports
# =============================================================================

def create_agent_graph_client(config: Optional[AgentGraphConfig] = None) -> AgentGraphClient:
    """Create an AgentGraphClient instance.
    
    Args:
        config: Optional configuration
        
    Returns:
        AgentGraphClient instance
    """
    client = AgentGraphClient(config)
    client.initialize()
    return client


__all__ = [
    "AgentGraphConfig",
    "AgentTokenCache",
    "CertificateHelper",
    "AgentGraphClient",
    "create_agent_graph_client",
]
