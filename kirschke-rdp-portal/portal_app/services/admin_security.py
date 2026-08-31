"""Local password gate for installations without a central directory service."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path


PBKDF2_ITERATIONS = 310_000


class LocalAdminPasswordStore:
    """Persist only a salted password hash in the current Windows profile."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
            path = Path(local_data) / "KirschkeRDPPortal" / "admin-security.json"
        self.path = path

    def is_configured(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return bool(data.get("salt") and data.get("password_hash"))
        except (OSError, TypeError, ValueError):
            return False

    def set_password(self, password: str) -> None:
        if len(password) < 10:
            raise ValueError("Das Admin-Passwort muss mindestens 10 Zeichen haben.")
        salt = secrets.token_bytes(16)
        password_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": 1,
                    "algorithm": "PBKDF2-HMAC-SHA256",
                    "iterations": PBKDF2_ITERATIONS,
                    "salt": base64.b64encode(salt).decode("ascii"),
                    "password_hash": base64.b64encode(password_hash).decode("ascii"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def verify_password(self, password: str) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            salt = base64.b64decode(data["salt"])
            expected = base64.b64decode(data["password_hash"])
            iterations = int(data.get("iterations", PBKDF2_ITERATIONS))
        except (KeyError, OSError, TypeError, ValueError):
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(candidate, expected)


def directory_mode() -> str:
    """Use local mode by default; AD is opt-in after infrastructure setup."""
    value = (os.environ.get("RDP_PORTAL_DIRECTORY_MODE") or "local").strip().casefold()
    return "active_directory" if value in {"ad", "active_directory", "active-directory"} else "local"


__all__ = ["LocalAdminPasswordStore", "directory_mode"]
