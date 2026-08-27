"""Mock authentication for Phase 1 development."""

from typing import Optional
from dataclasses import dataclass
from portal_app.models.user import User, UserRole, MockUser


@dataclass
class MockAuthProvider:
    """Mock authentication provider for development."""
    
    current_user: Optional[User] = None
    
    def __init__(self):
        """Initialize with default mock user."""
        self.current_user = MockUser.create_user()
    
    def login(self) -> bool:
        """Mock login - always succeeds."""
        self.current_user = MockUser.create_user()
        return True
    
    def login_as_admin(self) -> bool:
        """Mock admin login."""
        self.current_user = MockUser.create_admin()
        return True
    
    def logout(self) -> None:
        """Mock logout."""
        self.current_user = None
    
    def get_current_user(self) -> Optional[User]:
        """Get the current authenticated user."""
        return self.current_user
    
    def is_authenticated(self) -> bool:
        """Check if a user is authenticated."""
        return self.current_user is not None
    
    def get_token(self) -> Optional[str]:
        """Get authentication token (mock)."""
        if self.current_user:
            return f"mock-token-{self.current_user.object_id}"
        return None


__all__ = ["MockAuthProvider"]
