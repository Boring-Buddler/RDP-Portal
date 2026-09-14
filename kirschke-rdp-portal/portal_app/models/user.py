"""User model for Kirschke RDP Workstation Portal."""

from dataclasses import dataclass, field

from shared.enums import UserRole
from shared.identity import WindowsIdentity


@dataclass
class User:
    """User model representing an authenticated user."""

    object_id: str
    upn: str
    display_name: str
    email: str | None = None
    role: UserRole = UserRole.USER
    is_authenticated: bool = True
    rdp_username: str | None = None
    rdp_domain: str | None = None
    # The process identity is detected at startup and is deliberately not
    # editable or persisted. It identifies an own Windows session in the UI;
    # the native logoff path still verifies the SID immediately before use.
    windows_identity: str | None = None
    # The SID of that same process account, when Windows reported one. Names are
    # what a person reads; this is what Windows authorizes against, so it is the
    # form the session comparison prefers.
    windows_sid: str | None = None
    # Further Windows accounts this person says are also them, for example a local
    # account on a lab machine. Learned when the portal connects as one of them and
    # editable in the user settings. See windows_accounts() for why this is safe.
    own_accounts: list[str] = field(default_factory=list)

    def windows_accounts(self) -> list[WindowsIdentity]:
        """Every Windows account that counts as this person in the interface.

        The process identity is proven by Windows.  The additional accounts are a
        claim, not proof -- they only widen what the portal labels as "your
        session".  Nothing is granted by them: Windows still asks for that
        account's password on connect, and the agent authorizes a logoff on its
        own, so a wrong entry costs a refused attempt and nothing else.
        """
        accounts = [self.windows_account()]
        accounts.extend(
            WindowsIdentity.from_names(down_level=name) for name in self.own_accounts
        )
        return [account for account in accounts if account.for_display()]

    def claim_account(self, account: str | None) -> bool:
        """Remember one more account as this person's own; True if it was new."""
        from shared.login_accounts import validate_login_account

        if not account:
            return False
        try:
            name = validate_login_account(account)
        except ValueError:
            return False
        known = {self.windows_identity or "", *self.own_accounts}
        if any(existing.casefold() == name.casefold() for existing in known if existing):
            return False
        self.own_accounts.append(name)
        return True

    def windows_account(self) -> WindowsIdentity:
        """The Windows account this portal process runs as.

        Deliberately carries no UPN: ``upn`` may come from the portal sign-in,
        which is not necessarily the account that owns this Windows session.
        """
        return WindowsIdentity.from_names(
            down_level=self.windows_identity,
            sid=self.windows_sid,
        )

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

    def get_rdp_username(self) -> str | None:
        """Return the Windows-compatible default RDP username."""
        if not self.rdp_username:
            return None
        if self.rdp_domain and "\\" not in self.rdp_username and "@" not in self.rdp_username:
            return f"{self.rdp_domain}\\{self.rdp_username}"
        return self.rdp_username


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
            rdp_username="administrator",
            rdp_domain="KIRSCHKE",
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
            rdp_username="user",
            rdp_domain="KIRSCHKE",
        )


__all__ = ["User", "UserRole", "MockUser"]
