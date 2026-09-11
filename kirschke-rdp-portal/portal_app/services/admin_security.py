"""Local password gate for installations without a central directory service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from shared.file_io import write_json_atomic


PBKDF2_ITERATIONS = 310_000


class LocalAdminPasswordStore:
    """Persist only a salted password hash in the current Windows profile."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
            path = Path(local_data) / "KirschkeRDPPortal" / "admin-security.json"
        self.path = path

    def is_configured(self) -> bool:
        # A damaged existing file must not reopen first-time password setup.
        return self.path.exists()

    def set_password(self, password: str) -> None:
        if len(password) < 10:
            raise ValueError("Das Admin-Passwort muss mindestens 10 Zeichen haben.")
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
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            salt = base64.b64decode(data["salt"], validate=True)
            expected = base64.b64decode(data["password_hash"], validate=True)
            iterations = int(data.get("iterations", PBKDF2_ITERATIONS))
            if not 100_000 <= iterations <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
                return False
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        except (KeyError, OSError, TypeError, ValueError, AttributeError):
            return False
        return hmac.compare_digest(candidate, expected)


def directory_mode() -> str:
    """Use local mode by default; AD is opt-in after infrastructure setup."""
    value = (os.environ.get("RDP_PORTAL_DIRECTORY_MODE") or "local").strip().casefold()
    return "active_directory" if value in {"ad", "active_directory", "active-directory"} else "local"


__all__ = ["LocalAdminPasswordStore", "directory_mode"]
