"""Local password gate for installations without a central directory service.

Scope, so the gate is not mistaken for more than it is: the hash lives in the
signed-in user's own profile, which that user can delete to trigger first-time
setup again.  This separates roles in the interface and keeps casual changes out
of the shared inventory; it is not a boundary against the person sitting at the
machine.  The controls that matter are enforced by Windows -- the share ACL on the
shared store, the admin group in AD mode, and real target credentials for an
administrative signout.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from shared.file_io import write_json_atomic

PBKDF2_ITERATIONS = 310_000

#: Failed attempts before the gate pauses, and how long it then refuses.
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 900


class AdminLockoutError(RuntimeError):
    """Raised while the local password gate is paused after failed attempts."""

    def __init__(self, remaining_seconds: int) -> None:
        self.remaining_seconds = remaining_seconds
        minutes = max(1, (remaining_seconds + 59) // 60)
        super().__init__(
            f"Zu viele Fehlversuche. Der Adminzugang ist für {minutes} Minute(n) gesperrt."
        )


class LocalAdminPasswordStore:
    """Persist only a salted password hash in the current Windows profile."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
            path = Path(local_data) / "KirschkeRDPPortal" / "admin-security.json"
        self.path = path
        # Per-process, deliberately not persisted: a counter in the user's own
        # file would be as removable as the hash next to it. This slows down
        # guessing in a running portal, which is what it can honestly achieve.
        self._failed_attempts = 0
        self._locked_until = 0.0

    def is_configured(self) -> bool:
        # A damaged existing file must not reopen first-time password setup.
        return self.path.exists()

    def lockout_remaining_seconds(self) -> int:
        return max(0, int(round(self._locked_until - time.monotonic())))

    def _register_failure(self) -> None:
        self._failed_attempts += 1
        if self._failed_attempts >= MAX_FAILED_ATTEMPTS:
            self._locked_until = time.monotonic() + LOCKOUT_SECONDS
            self._failed_attempts = 0

    def set_password(self, password: str) -> None:
        if len(password) < 10:
            raise ValueError("Das Admin-Passwort muss mindestens 10 Zeichen haben.")
        self._failed_attempts = 0
        self._locked_until = 0.0
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(
            self.path,
                {
                    "version": 1,
                    "algorithm": "PBKDF2-HMAC-SHA256",
                    "iterations": PBKDF2_ITERATIONS,
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "password_hash": base64.b64encode(password_hash).decode("ascii"),
                },
        )

    def verify_password(self, password: str) -> bool:
        """Check one password, counting failures towards a temporary lockout.

        Raises:
            AdminLockoutError: too many failed attempts in this portal session.
        """
        remaining = self.lockout_remaining_seconds()
        if remaining:
            raise AdminLockoutError(remaining)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            salt = base64.b64decode(data["salt"], validate=True)
            expected = base64.b64decode(data["password_hash"], validate=True)
            iterations = int(data.get("iterations", PBKDF2_ITERATIONS))
            if not 100_000 <= iterations <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
                self._register_failure()
                return False
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        except (KeyError, OSError, TypeError, ValueError, AttributeError):
            self._register_failure()
            return False
        if hmac.compare_digest(candidate, expected):
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
    "LocalAdminPasswordStore",
    "directory_mode",
]
