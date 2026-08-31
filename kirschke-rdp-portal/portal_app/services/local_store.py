"""Small JSON store used by the locally testable application build."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser, UserRole
from portal_app.models.workstation import Workstation
from shared.schemas import SessionEventSchema, WorkstationSchema


class LocalStore:
    """Persist test data without requiring SharePoint or Entra ID."""

    def __init__(self, path: Path | None = None) -> None:
        self.config_path = self._config_path()
        self._uses_default_location = path is None
        if path is None:
            path = self._configured_directory() / "portal-state.json"
        self.path = path
        self.events_path = self.path.parent / "portal-events.jsonl"
        self.theme_mode = "system"
        self._state_signature: tuple[int, int] | None = None
        self._events_signature: tuple[int, int] | None = None

    @staticmethod
    def default_directory() -> Path:
        user_profile = Path(os.environ.get("USERPROFILE") or Path.home())
        return (
            user_profile
            / "Prof. Dr.-Ing. Dieter Kirschke GmbH & Co. KG"
            / "IB Kirschke - Dokumente"
            / "90"
            / "_K.I. Strategie"
            / "Testprogramme"
            / "RDP-Portal"
        )

    @staticmethod
    def _config_path() -> Path:
        local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
        return Path(local_data) / "KirschkeRDPPortal" / "storage-config.json"

    def _configured_directory(self) -> Path:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            location = config.get("storage_directory")
            if location:
                return Path(location)
        except (OSError, ValueError, TypeError):
            pass
        # If the local configuration was removed, a redirect marker in the
        # original SharePoint folder still makes a previous move recoverable.
        marker = self.default_directory() / "storage-location.json"
        try:
            location = json.loads(marker.read_text(encoding="utf-8")).get("storage_directory")
            if location:
                return Path(location)
        except (OSError, ValueError, TypeError):
            pass
        return self.default_directory()

    @property
    def directory(self) -> Path:
        return self.path.parent

    @staticmethod
    def _signature(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _remember_signatures(self) -> None:
        self._state_signature = self._signature(self.path)
        self._events_signature = self._signature(self.events_path)

    def has_external_changes(self) -> bool:
        """Return whether the OneDrive/SharePoint mirror changed since the last read/write."""
        return (
            self._signature(self.path) != self._state_signature
            or self._signature(self.events_path) != self._events_signature
        )

    def _save_directory_config(self, directory: Path | None = None) -> None:
        if not self._uses_default_location:
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(
                {"storage_directory": str(directory or self.directory), "version": 1},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _write_redirect_marker(previous_directory: Path, new_directory: Path) -> None:
        """Leave a small, human-readable recovery pointer at the old location."""
        marker = previous_directory / "storage-location.json"
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "storage_directory": str(new_directory),
                    "message": "RDP-Portal-Dateien wurden in diesen Ordner verschoben.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(marker)

    def load(
        self,
        fallback_workstations: list[Workstation],
        fallback_user: MockUser,
    ) -> tuple[list[Workstation], MockUser, list[Reservation]]:
        if not self.path.exists():
            self._remember_signatures()
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
            else:
                self._remember_signatures()
            return workstations or fallback_workstations, user, reservations
        except (OSError, ValueError, KeyError, TypeError):
            self._remember_signatures()
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
        self._remember_signatures()

    def load_events(self) -> list[SessionEvent]:
        """Load the append-only portal event log; malformed individual lines are skipped."""
        if not self.events_path.exists():
            return []
        events: list[SessionEvent] = []
        try:
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    schema = SessionEventSchema.model_validate_json(line)
                    events.append(SessionEvent.from_schema(schema))
                except ValueError:
                    continue
        except OSError:
            return []
        return events

    def append_event(self, event: SessionEvent) -> None:
        """Append one portal event without retaining credentials or passwords."""
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = event.to_schema().model_dump_json()
        with self.events_path.open("a", encoding="utf-8") as event_file:
            event_file.write(serialized + "\n")
        self._remember_signatures()

    def initialize_event_log(self) -> None:
        """Create the empty append-only log on first portal startup."""
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self._remember_signatures()

    def relocate(self, directory: Path, move_files: bool = True) -> None:
        """Switch storage folders and copy-verify existing state and event files first."""
        previous_directory = self.directory
        target_directory = directory.expanduser().resolve()
        target_directory.mkdir(parents=True, exist_ok=True)
        target_state = target_directory / "portal-state.json"
        target_events = target_directory / "portal-events.jsonl"
        if target_directory == self.directory:
            self._save_directory_config()
            return
        pairs = [
            (source, target)
            for source, target in ((self.path, target_state), (self.events_path, target_events))
            if source.exists()
        ]
        for _, target in pairs:
            if target.exists():
                raise FileExistsError(f"Zieldatei existiert bereits: {target.name}")
        for source, target in pairs:
            shutil.copy2(source, target)
            if source.suffix == ".json":
                json.loads(target.read_text(encoding="utf-8"))
        # The reference is written before the original files are removed.  If
        # it cannot be written, the original data remains intact.
        self._save_directory_config(target_directory)
        self._write_redirect_marker(previous_directory, target_directory)
        if move_files:
            for source, _ in pairs:
                source.unlink()
        self.path = target_state
        self.events_path = target_events
        self._remember_signatures()


__all__ = ["LocalStore"]
