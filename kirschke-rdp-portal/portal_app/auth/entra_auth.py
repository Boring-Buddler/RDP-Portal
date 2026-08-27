"""Microsoft Entra ID authentication for Kirschke RDP Workstation Portal.

This module provides authentication using MSAL (Microsoft Authentication Library)
with Microsoft Entra ID (formerly Azure AD). It handles:
- Interactive user authentication
- Silent token acquisition
- Token caching
- User role extraction from Entra ID groups
- Token management and refresh
"""

import os
import json
import logging
import webbrowser
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock

import msal
from msal import PublicClientApplication, ConfidentialClientApplication

from shared.enums import UserRole
from portal_app.models.user import User

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class EntraAuthConfig:
    """Configuration for Entra ID authentication."""
    
    tenant_id: str = os.getenv("TENANT_ID", "")
    client_id: str = os.getenv("PORTAL_CLIENT_ID", "")
    authority: str = os.getenv("AUTHORITY", "")
    redirect_uri: str = os.getenv("PORTAL_REDIRECT_URI", "http://localhost:8000/auth/callback")
    scopes: list[str] = field(default_factory=lambda: [
        "User.Read",
        "Group.ReadAll",
        "Sites.Read.All",
        "Sites.ReadWrite.All",
    ])
    cache_path: str = os.getenv("ENTRA_CACHE_PATH", "")
    
    # Group IDs for role mapping
    users_group_id: str = os.getenv("RDP_PORTAL_USERS_GROUP_ID", "")
    admins_group_id: str = os.getenv("RDP_PORTAL_ADMINS_GROUP_ID", "")
    
    @classmethod
    def from_env(cls) -> "EntraAuthConfig":
        """Create configuration from environment variables."""
        scopes_str = os.getenv("PORTAL_SCOPES", "")
        scopes = [s.strip() for s in scopes_str.split(",")] if scopes_str else [
            "User.Read",
            "Group.ReadAll",
            "Sites.Read.All",
            "Sites.ReadWrite.All",
        ]
        
        # Build authority if not set
        authority = os.getenv("AUTHORITY", "")
        if not authority and os.getenv("TENANT_ID"):
            authority = f"https://login.microsoftonline.com/{os.getenv('TENANT_ID')}"
        
        # Set cache path if not set
        cache_path = os.getenv("ENTRA_CACHE_PATH", "")
        if not cache_path:
            cache_dir = Path.home() / ".kirschke" / "rdp-portal" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = str(cache_dir / "entra_cache.json")
        
        return cls(
            tenant_id=os.getenv("TENANT_ID", ""),
            client_id=os.getenv("PORTAL_CLIENT_ID", ""),
            authority=authority,
            redirect_uri=os.getenv("PORTAL_REDIRECT_URI", "http://localhost:8000/auth/callback"),
            scopes=scopes,
            cache_path=cache_path,
            users_group_id=os.getenv("RDP_PORTAL_USERS_GROUP_ID", ""),
            admins_group_id=os.getenv("RDP_PORTAL_ADMINS_GROUP_ID", ""),
        )
    
    def validate(self) -> bool:
        """Validate that required configuration is present."""
        required = [self.tenant_id, self.client_id]
        return all(required)


# =============================================================================
# Token Cache
# =============================================================================

class TokenCache:
    """Persistent token cache for MSAL."""
    
    def __init__(self, cache_path: str):
        """Initialize the token cache.
        
        Args:
            cache_path: Path to the cache file
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
            logger.warning(f"Failed to load token cache: {e}")
            self._cache = {}
    
    def _save(self) -> None:
        """Save cache to file."""
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save token cache: {e}")
    
    def get(self) -> dict:
        """Get the cache dictionary."""
        with self._lock:
            return self._cache.copy()
    
    def set(self, cache: dict) -> None:
        """Set the cache dictionary."""
        with self._lock:
            self._cache = cache.copy()
            self._save()
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache = {}
            self._save()
    
    def remove_account(self, account_id: str) -> None:
        """Remove a specific account from the cache."""
        with self._lock:
            if "Account" in self._cache:
                accounts = {
                    k: v for k, v in self._cache["Account"].items()
                    if k != account_id
                }
                self._cache["Account"] = accounts
                self._save()


# =============================================================================
# Entra ID Authentication Provider
# =============================================================================

@dataclass
class EntraUserInfo:
    """User information from Entra ID."""
    
    object_id: str
    upn: str
    display_name: str
    email: Optional[str] = None
    group_ids: list[str] = field(default_factory=list)
    is_member_of_users_group: bool = False
    is_member_of_admins_group: bool = False
    
    def get_role(self) -> UserRole:
        """Determine user role based on group membership."""
        if self.is_member_of_admins_group:
            return UserRole.ADMIN
        if self.is_member_of_users_group:
            return UserRole.USER
        return UserRole.USER  # Default to USER if not in any group


class EntraAuthProvider:
    """Microsoft Entra ID authentication provider using MSAL.
    
    This provider handles interactive user authentication, token acquisition,
    and user role extraction from Entra ID groups.
    
    Example usage:
        auth = EntraAuthProvider()
        if auth.login():
            user = auth.get_current_user()
            token = auth.get_token()
    """
    
    def __init__(self, config: Optional[EntraAuthConfig] = None):
        """Initialize the Entra ID authentication provider.
        
        Args:
            config: Optional configuration. If None, uses environment variables.
        """
        self.config = config or EntraAuthConfig.from_env()
        self._app: Optional[PublicClientApplication] = None
        self._cache: Optional[TokenCache] = None
        self._current_user: Optional[User] = None
        self._current_account: Optional[dict] = None
        self._user_info: Optional[EntraUserInfo] = None
        
        self._initialize_app()
    
    def _initialize_app(self) -> None:
        """Initialize the MSAL PublicClientApplication."""
        if not self.config.validate():
            logger.warning("Entra ID configuration is incomplete. Authentication will fail.")
        
        # Create token cache
        self._cache = TokenCache(self.config.cache_path)
        
        # Create MSAL app with persistent cache
        self._app = PublicClientApplication(
            client_id=self.config.client_id,
            authority=self.config.authority,
            cache=self._create_msal_cache(),
        )
    
    def _create_msal_cache(self) -> Any:
        """Create an MSAL cache instance with persistent storage."""
        class PersistentCache(msal.SerializableTokenCache):
            """Custom token cache that persists to file."""
            
            def __init__(self, cache: TokenCache):
                super().__init__()
                self._cache = cache
            
            def add(self, event: dict) -> None:
                """Add event to cache."""
                super().add(event)
                self._cache.set(super().serialize())
            
            def remove(self, event: dict) -> None:
                """Remove event from cache."""
                super().remove(event)
                self._cache.set(super().serialize())
            
            def has_state_changed(self) -> bool:
                """Check if cache state has changed."""
                return True  # Always persist changes
        
        cache = PersistentCache(self._cache)  # type: ignore
        
        # Load existing cache
        cached_data = self._cache.get()
        if cached_data:
            cache.deserialize(cached_data)
        
        return cache
    
    def is_configured(self) -> bool:
        """Check if authentication is properly configured."""
        return self.config.validate()
    
    def is_authenticated(self) -> bool:
        """Check if a user is currently authenticated."""
        return self._current_user is not None
    
    def get_current_user(self) -> Optional[User]:
        """Get the currently authenticated user."""
        return self._current_user
    
    def get_user_info(self) -> Optional[EntraUserInfo]:
        """Get detailed user information from Entra ID."""
        return self._user_info
    
    def login(self, open_browser: bool = True) -> bool:
        """Perform interactive login with Microsoft Entra ID.
        
        This opens the default browser for authentication and waits for
        the user to complete the login flow.
        
        Args:
            open_browser: Whether to automatically open the browser
            
        Returns:
            True if login succeeded, False otherwise
        """
        if not self.is_configured():
            logger.error("Entra ID authentication is not configured")
            return False
        
        if not self._app:
            logger.error("MSAL application not initialized")
            return False
        
        try:
            # Get accounts from cache
            accounts = self._app.get_accounts()
            
            # Try silent acquisition first
            result = self._try_silent_acquisition(accounts)
            if result:
                return True
            
            # Perform interactive login
            logger.info("Starting interactive login...")
            
            # Build redirect URI
            redirect_uri = self.config.redirect_uri
            
            # Perform device flow for CLI applications
            flow = self._app.initiate_device_flow(
                scopes=self.config.scopes,
                device_flow_callback=self._device_flow_callback
            )
            
            if open_browser:
                webbrowser.open(flow["verification_uri"])
            
            print(f"\nPlease open this URL in your browser: {flow['verification_uri']}")
            print(f"Enter code: {flow['user_code']}")
            print(f"Expires in: {flow['expires_in']} seconds\n")
            
            # Wait for token
            result = self._app.acquire_token_by_device_flow(flow)
            
            if result and "access_token" in result:
                return self._handle_successful_auth(result)
            
            logger.error("Device flow login failed")
            return False
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False
    
    def _device_flow_callback(self, flow: dict) -> None:
        """Callback for device flow to display information."""
        print(f"\nDevice flow: {flow.get('verification_uri', '')}")
        print(f"Code: {flow.get('user_code', '')}")
    
    def _try_silent_acquisition(self, accounts: list) -> bool:
        """Try to acquire token silently from cache.
        
        Args:
            accounts: List of cached accounts
            
        Returns:
            True if silent acquisition succeeded, False otherwise
        """
        if not accounts:
            return False
        
        try:
            for account in accounts:
                result = self._app.acquire_token_silent(
                    scopes=self.config.scopes,
                    account=account,
                )
                
                if result and "access_token" in result:
                    return self._handle_successful_auth(result, account)
        except Exception as e:
            logger.debug(f"Silent token acquisition failed: {e}")
        
        return False
    
    def _handle_successful_auth(self, result: dict, account: Optional[dict] = None) -> bool:
        """Handle successful authentication result.
        
        Args:
            result: Authentication result from MSAL
            account: Optional account information
            
        Returns:
            True if user information was successfully retrieved
        """
        try:
            # Store the account
            if account:
                self._current_account = account
            elif "id_token_claims" in result:
                self._current_account = result["id_token_claims"]
            
            # Extract user info from ID token claims
            claims = result.get("id_token_claims", {})
            user_info = self._extract_user_info_from_claims(claims)
            
            if not user_info:
                # Fetch user info from Graph API
                user_info = self._fetch_user_info_from_graph(result.get("access_token"))
            
            if not user_info:
                logger.error("Could not retrieve user information")
                return False
            
            self._user_info = user_info
            
            # Determine role
            role = user_info.get_role()
            
            # Create user object
            self._current_user = User(
                object_id=user_info.object_id,
                upn=user_info.upn,
                display_name=user_info.display_name,
                email=user_info.email,
                role=role,
                is_authenticated=True,
            )
            
            logger.info(f"Successfully authenticated user: {user_info.upn}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to handle authentication result: {e}")
            return False
    
    def _extract_user_info_from_claims(self, claims: dict) -> Optional[EntraUserInfo]:
        """Extract user information from ID token claims.
        
        Args:
            claims: ID token claims from MSAL
            
        Returns:
            EntraUserInfo if claims contain required information, None otherwise
        """
        try:
            object_id = claims.get("oid") or claims.get("sub")
            upn = claims.get("upn") or claims.get("preferred_username")
            display_name = claims.get("name")
            email = claims.get("email") or claims.get("mail")
            
            if not all([object_id, upn, display_name]):
                return None
            
            # Extract group IDs from claims
            group_ids: list[str] = []
            groups_claim = claims.get("groups", [])
            if isinstance(groups_claim, list):
                group_ids = [str(g) for g in groups_claim]
            
            return EntraUserInfo(
                object_id=object_id,
                upn=upn,
                display_name=display_name,
                email=email,
                group_ids=group_ids,
                is_member_of_users_group=self.config.users_group_id in group_ids,
                is_member_of_admins_group=self.config.admins_group_id in group_ids,
            )
            
        except Exception as e:
            logger.debug(f"Failed to extract user info from claims: {e}")
            return None
    
    def _fetch_user_info_from_graph(self, access_token: Optional[str]) -> Optional[EntraUserInfo]:
        """Fetch user information from Microsoft Graph API.
        
        Args:
            access_token: OAuth2 access token
            
        Returns:
            EntraUserInfo if retrieved successfully, None otherwise
        """
        if not access_token:
            return None
        
        try:
            import requests
            
            # Get user info
            headers = {
                "Authorization": f"Bearer {access_token}",
                "ConsistencyLevel": "eventual",
            }
            
            # Get user details
            user_url = "https://graph.microsoft.com/v1.0/me"
            user_response = requests.get(user_url, headers=headers, timeout=30)
            
            if user_response.status_code != 200:
                logger.warning(f"Failed to get user info: {user_response.status_code}")
                return None
            
            user_data = user_response.json()
            
            # Get group memberships
            groups_url = "https://graph.microsoft.com/v1.0/me/memberOf"
            groups_response = requests.get(groups_url, headers=headers, timeout=30)
            
            group_ids: list[str] = []
            if groups_response.status_code == 200:
                groups_data = groups_response.json().get("value", [])
                group_ids = [g.get("id", "") for g in groups_data]
            
            # Check if user is in admin or users group
            is_admin = self.config.admins_group_id in group_ids
            is_user = self.config.users_group_id in group_ids
            
            return EntraUserInfo(
                object_id=user_data.get("id", ""),
                upn=user_data.get("userPrincipalName", ""),
                display_name=user_data.get("displayName", ""),
                email=user_data.get("mail") or user_data.get("userPrincipalName"),
                group_ids=group_ids,
                is_member_of_users_group=is_user,
                is_member_of_admins_group=is_admin,
            )
            
        except Exception as e:
            logger.warning(f"Failed to fetch user info from Graph: {e}")
            return None
    
    def get_token(self) -> Optional[str]:
        """Get the current access token.
        
        Returns:
            Access token if authenticated, None otherwise
        """
        if not self.is_authenticated():
            return None
        
        if not self._app:
            return None
        
        try:
            accounts = self._app.get_accounts()
            if not accounts:
                return None
            
            result = self._app.acquire_token_silent(
                scopes=self.config.scopes,
                account=accounts[0],
            )
            
            if result and "access_token" in result:
                return result["access_token"]
            
            # Try to get token for any scope
            result = self._app.acquire_token_silent(
                scopes=["User.Read"],
                account=accounts[0],
            )
            
            if result and "access_token" in result:
                return result["access_token"]
            
        except Exception as e:
            logger.warning(f"Failed to get access token: {e}")
        
        return None
    
    def logout(self) -> None:
        """Log out the current user and clear authentication state."""
        try:
            if self._app and self._current_account:
                # Remove account from MSAL cache
                self._app.remove_account(self._current_account)
            
            if self._cache:
                # Clear persistent cache
                self._cache.clear()
            
            # Reset state
            self._current_user = None
            self._current_account = None
            self._user_info = None
            
            logger.info("User logged out successfully")
            
        except Exception as e:
            logger.error(f"Failed to logout: {e}")
        finally:
            self._current_user = None
            self._current_account = None
            self._user_info = None
    
    def get_accounts(self) -> list[dict]:
        """Get all cached accounts.
        
        Returns:
            List of cached account dictionaries
        """
        if not self._app:
            return []
        
        try:
            return self._app.get_accounts()
        except Exception as e:
            logger.warning(f"Failed to get accounts: {e}")
            return []
    
    def refresh_token(self) -> bool:
        """Refresh the access token.
        
        Returns:
            True if token was refreshed successfully, False otherwise
        """
        if not self.is_authenticated():
            return False
        
        if not self._app:
            return False
        
        try:
            accounts = self._app.get_accounts()
            if not accounts:
                return False
            
            result = self._app.acquire_token_silent(
                scopes=self.config.scopes,
                account=accounts[0],
            )
            
            if result and "access_token" in result:
                logger.info("Token refreshed successfully")
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Failed to refresh token: {e}")
            return False
    
    def get_token_expiry(self) -> Optional[datetime]:
        """Get the expiration time of the current access token.
        
        Returns:
            Token expiration datetime, or None if not authenticated
        """
        if not self.is_authenticated():
            return None
        
        if not self._app:
            return None
        
        try:
            accounts = self._app.get_accounts()
            if not accounts:
                return None
            
            result = self._app.acquire_token_silent(
                scopes=self.config.scopes,
                account=accounts[0],
            )
            
            if result and "expires_in" in result:
                return datetime.utcnow() + timedelta(seconds=result["expires_in"])
            
        except Exception as e:
            logger.debug(f"Failed to get token expiry: {e}")
        
        return None
    
    def is_token_expired(self) -> bool:
        """Check if the current token is expired or about to expire.
        
        Returns:
            True if token is expired or will expire within 5 minutes
        """
        expiry = self.get_token_expiry()
        if not expiry:
            return True
        
        return expiry <= datetime.utcnow() + timedelta(minutes=5)


# =============================================================================
# Factory and Exports
# =============================================================================

def create_auth_provider() -> EntraAuthProvider:
    """Factory function to create an EntraAuthProvider.
    
    Returns:
        Configured EntraAuthProvider instance
    """
    return EntraAuthProvider()


__all__ = [
    "EntraAuthConfig",
    "TokenCache",
    "EntraUserInfo",
    "EntraAuthProvider",
    "create_auth_provider",
]
