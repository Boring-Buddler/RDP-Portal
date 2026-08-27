"""Authentication module for Kirschke RDP Workstation Portal."""

# Phase 2: Entra ID authentication with MSAL
# For Phase 1, mock authentication is used

from portal_app.auth.mock_auth import MockAuthProvider
from portal_app.auth.entra_auth import (
    EntraAuthConfig,
    TokenCache,
    EntraUserInfo,
    EntraAuthProvider,
    create_auth_provider,
)

__all__ = [
    "MockAuthProvider",
    "EntraAuthConfig",
    "TokenCache",
    "EntraUserInfo",
    "EntraAuthProvider",
    "create_auth_provider",
]
