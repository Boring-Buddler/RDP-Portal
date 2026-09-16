"""Shared portal admin password shipped with every installation.

The release contains a salted hash. Profile-local password files do not affect
this gate. Windows still authorizes filesystem access and target session logoff.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

PBKDF2_ITERATIONS = 310_000
# One release-wide verifier; changing it requires distributing an updated portal.
_ADMIN_SALT = bytes.fromhex("da3dd751c709944fcbc24f61dd56af61")
_ADMIN_PASSWORD_HASH = bytes.fromhex(
    "88dffe4e93012acd75dbb468e7e66a882ad9ebe7ac64327e6ebcc04926a9b98d"
)

#: Failed attempts before the gate pauses, and how long it then refuses.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900


class AdminLockoutError(RuntimeError):
    """Raised while the portal password gate is paused after failed attempts."""

    def __init__(self, remaining_seconds: int) -> None:
        self.remaining_seconds = remaining_seconds
        minutes = max(1, (remaining_seconds + 59) // 60)
        super().__init__(
            f"Zu viele Fehlversuche. Der Adminzugang ist für {minutes} Minute(n) gesperrt."
        )


class GlobalAdminPasswordVerifier:
    """Verify the same bundled admin credential on every portal PC."""

    def __init__(self) -> None:
        # Rate limiting applies to this running portal, independently per PC.
        self._failed_attempts = 0
        self._locked_until = 0.0

    def lockout_remaining_seconds(self) -> int:
        return max(0, int(round(self._locked_until - time.monotonic())))

    def _register_failure(self) -> None:
        self._failed_attempts += 1
        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._locked_until = time.monotonic() + LOCKOUT_SECONDS
            self._failed_attempts = 0

    def verify_password(self, password: str) -> bool:
        """Check one password, counting failures towards a temporary lockout.

        Raises:
            AdminLockoutError: too many failed attempts in this portal session.
        """
        remaining = self.lockout_remaining_seconds()
        if remaining:
            raise AdminLockoutError(remaining)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _ADMIN_SALT, PBKDF2_ITERATIONS
        )
        if hmac.compare_digest(candidate, _ADMIN_PASSWORD_HASH):
            self._failed_attempts = 0
            return True
        self._register_failure()
        return False


def directory_mode() -> str:
    """Use local mode by default; AD is opt-in after infrastructure setup."""
    value = (os.environ.get("RDP_PORTAL_DIRECTORY_MODE") or "local").strip().casefold()
    return "active_directory" if value in {"ad", "active_directory", "active-directory"} else "local"


__all__ = [
    "LOCKOUT_SECONDS",
    "MAX_FAILED_ATTEMPTS",
    "AdminLockoutError",
    "GlobalAdminPasswordVerifier",
    "directory_mode",
]
