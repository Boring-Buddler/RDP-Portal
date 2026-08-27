"""User model for Kirschke RDP Workstation Portal."""

from typing import Optional
from dataclasses import dataclass
from enum import Enum
from shared.enums import UserRole


class UserRole(str, Enum):
    """User roles in the system."""
    USER = "user"
    ADMIN = "admin"


@dataclass
class User:
    """User model representing an authenticated user."""
    
    object_id: str
    upn: str
    display_name: str
    email: Optional[str] = None
    role: UserRole = UserRole.USER
    is_authenticated: bool = True
    
    @property
    def is_admin(self) -> bool:
        """Check if user is an administrator."""
        return self.role == UserRole.ADMIN
    
    def can_manage_workstations(self) -> bool:
        """Check if user can manage workstations."""
        return self.is_admin
    
    def can_manage_users(self) -> bool:
        """Check if user can manage users."""
        return self.is_admin
    
    def can_view_all_sessions(self) -> bool:
        """Check if user can view all sessions."""
        return self.is_admin
    
    def can_execute_admin_commands(self) -> bool:
        """Check if user can execute admin commands."""
        return self.is_admin


@dataclass
class MockUser(User):
    """Mock user for development."""
    
    @classmethod
    def create_admin(cls) -> "MockUser":
        """Create a mock admin user."""
        return cls(
            object_id="admin-id-1234-5678-90ab-cdef12345678",
            upn="admin@prof-kirschke.de",
            display_name="System Administrator",
            email="admin@prof-kirschke.de",
            role=UserRole.ADMIN,
        )
    
    @classmethod
    def create_user(cls) -> "MockUser":
        """Create a mock regular user."""
        return cls(
            object_id="user-id-1234-5678-90ab-cdef12345678",
            upn="user@prof-kirschke.de",
            display_name="Regular User",
            email="user@prof-kirschke.de",
            role=UserRole.USER,
        )


__all__ = ["User", "UserRole", "MockUser"]
