"""Small JSON store used by the locally testable application build."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from portal_app.models.reservation import Reservation
from portal_app.models.user import MockUser, UserRole
from portal_app.models.workstation import Workstation
from shared.schemas import WorkstationSchema


class LocalStore:
    """Persist test data without requiring SharePoint or Entra ID."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
            path = Path(local_data) / "KirschkeRDPPortal" / "test-data.json"
        self.path = path
        self.theme_mode = "system"

    def load(
        self,
        fallback_workstations: list[Workstation],
        fallback_user: MockUser,
    ) -> tuple[list[Workstation], MockUser, list[Reservation]]:
        if not self.path.exists():
            return fallback_workstations, fallback_user, []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # Older local files used "light" as an implicit default. Treat it
            # as the new system-default mode rather than overriding Windows.
            stored_theme = data.get("theme_mode")
            is_current_format = data.get("version", 0) >= 3
            self.theme_mode = (
                stored_theme if is_current_format and stored_theme in {"system", "light", "dark"}
                else "dark" if stored_theme == "dark" else "system"
            )
            workstations = [
                Workstation.from_schema(WorkstationSchema.model_validate(item))
                for item in data.get("workstations", [])
            ]
            # Test builds before the machine editor used generated usernames such
            # as user1@prof-kirschke.de.  They are placeholders, not intentional
            # per-machine credentials, and would otherwise override whoami.
            removed_legacy_placeholders = False
            for workstation in workstations:
                username_hint = workstation.username_hint or ""
                if re.fullmatch(r"user\d+@prof-kirschke\.de", username_hint, re.IGNORECASE):
                    workstation.username_hint = None
                    removed_legacy_placeholders = True
            user_data = data.get("user", {})
            user = MockUser(
                object_id=user_data.get("object_id", fallback_user.object_id),
                upn=user_data.get("upn", fallback_user.upn),
                display_name=user_data.get("display_name", fallback_user.display_name),
                email=user_data.get("email", fallback_user.email),
                role=UserRole(user_data.get("role", fallback_user.role.value)),
                rdp_username=user_data.get("rdp_username"),
                rdp_domain=user_data.get("rdp_domain"),
            )
            reservations = [Reservation.from_dict(item) for item in data.get("reservations", [])]
            if removed_legacy_placeholders:
                self.save(workstations, user, reservations, theme_mode=self.theme_mode)
            return workstations or fallback_workstations, user, reservations
        except (OSError, ValueError, KeyError, TypeError):
            return fallback_workstations, fallback_user, []

    def save(
        self,
        workstations: list[Workstation],
        user: MockUser,
        reservations: list[Reservation],
        theme_mode: str = "system",
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 3,
            "theme_mode": theme_mode if theme_mode in {"system", "light", "dark"} else "system",
            "workstations": [ws.to_schema().model_dump(mode="json") for ws in workstations],
            "user": {
                "object_id": user.object_id,
                "upn": user.upn,
                "display_name": user.display_name,
                "email": user.email,
                "role": user.role.value,
                "rdp_username": user.rdp_username,
                "rdp_domain": user.rdp_domain,
            },
            "reservations": [reservation.to_dict() for reservation in reservations],
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)


__all__ = ["LocalStore"]
