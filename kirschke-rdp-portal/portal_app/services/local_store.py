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


class StoreConflictError(RuntimeError):
    """Raised when two portal instances changed the same shared record."""


class LocalStore:
    """Persist test data without requiring SharePoint or Entra ID."""

    def __init__(self, path: Path | None = None) -> None:
        self.config_path = self._config_path()
        self._uses_default_location = path is None
        if path is None:
            path = self._configured_directory() / "portal-state.json"
        self.path = path
        self.events_path = self.path.parent / "portal-events.jsonl"
        self.directory_users_path = self.path.parent / "portal-directory-users.json"
        self.preferences_path = (
            self.config_path.parent / "portal-preferences.json"
            if self._uses_default_location
            else self.path.with_name(f"{self.path.stem}-preferences.json")
        )
        self.theme_mode = "system"
        self._state_signature: tuple[int, int] | None = None
        self._events_signature: tuple[int, int] | None = None
        self._directory_users_signature: tuple[int, int] | None = None
        self._baseline_workstations: dict[str, dict] = {}
        self._baseline_reservations: dict[str, dict] = {}

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
        self._directory_users_signature = self._signature(self.directory_users_path)

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _user_from_data(data: dict, fallback: MockUser) -> MockUser:
        return MockUser(
            object_id=data.get("object_id", fallback.object_id),
            upn=data.get("upn", fallback.upn),
            display_name=data.get("display_name", fallback.display_name),
            email=data.get("email", fallback.email),
            role=UserRole(data.get("role", fallback.role.value)),
            rdp_username=data.get("rdp_username"),
            rdp_domain=data.get("rdp_domain"),
        )

    @staticmethod
    def _user_data(user: MockUser) -> dict:
        return {
            "object_id": user.object_id,
            "upn": user.upn,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role.value,
            "rdp_username": user.rdp_username,
            "rdp_domain": user.rdp_domain,
        }

    def _load_preferences(self, fallback: MockUser, legacy_data: dict | None = None) -> MockUser:
        data: dict = {}
        uses_legacy_data = False
        try:
            data = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = legacy_data or {}
            uses_legacy_data = bool(legacy_data)
        stored_theme = data.get("theme_mode")
        if uses_legacy_data and data.get("version", 0) < 3:
            self.theme_mode = "dark" if stored_theme == "dark" else "system"
        else:
            self.theme_mode = stored_theme if stored_theme in {"system", "light", "dark"} else "system"
        return self._user_from_data(data.get("user", {}), fallback)

    def _save_preferences(self, user: MockUser, theme_mode: str) -> None:
        self.theme_mode = theme_mode if theme_mode in {"system", "light", "dark"} else "system"
        self._write_json(
            self.preferences_path,
            {"version": 1, "theme_mode": self.theme_mode, "user": self._user_data(user)},
        )

    def _set_baseline(self, data: dict) -> None:
        self._baseline_workstations = {
            item["workstation_id"]: item for item in data.get("workstations", []) if item.get("workstation_id")
        }
        self._baseline_reservations = {
            item["reservation_id"]: item for item in data.get("reservations", []) if item.get("reservation_id")
        }

    @staticmethod
    def _merge_records(
        baseline: dict[str, dict],
        local_records: list[dict],
        remote_records: list[dict],
        identifier: str,
        label: str,
    ) -> list[dict]:
        """Three-way merge records; refuse a simultaneous edit of one record."""
        local = {item[identifier]: item for item in local_records if item.get(identifier)}
        remote = {item[identifier]: item for item in remote_records if item.get(identifier)}
        merged: dict[str, dict] = {}
        conflicts: list[str] = []
        for record_id in sorted(set(baseline) | set(local) | set(remote)):
            base = baseline.get(record_id)
            current = local.get(record_id)
            incoming = remote.get(record_id)
            if current == incoming:
                selected = current
            elif current == base:
                selected = incoming
            elif incoming == base:
                selected = current
            else:
                conflicts.append(record_id)
                continue
            if selected is not None:
                merged[record_id] = selected
        if conflicts:
            raise StoreConflictError(
                f"{label} wurde parallel bearbeitet: {', '.join(conflicts)}. "
                "Bitte aktualisieren und die Änderung erneut vornehmen."
            )
        return list(merged.values())

    def _merge_shared_data(self, remote_data: dict, local_data: dict) -> dict:
        """Merge an externally synced state file with the current portal changes."""
        return {
            "version": 4,
            "workstations": self._merge_records(
                self._baseline_workstations,
                local_data["workstations"],
                remote_data.get("workstations", []),
                "workstation_id",
                "Maschine",
            ),
            "reservations": self._merge_records(
                self._baseline_reservations,
                local_data["reservations"],
                remote_data.get("reservations", []),
                "reservation_id",
                "Reservierung",
            ),
        }

    def has_external_changes(self) -> bool:
        """Return whether the OneDrive/SharePoint mirror changed since the last read/write."""
        return (
            self._signature(self.path) != self._state_signature
            or self._signature(self.events_path) != self._events_signature
            or self._signature(self.directory_users_path) != self._directory_users_signature
        )

    @staticmethod
    def _normalise_accounts(accounts: list[str]) -> list[str]:
        """Return unique, non-empty directory accounts in a stable order."""
        unique: dict[str, str] = {}
        for account in accounts:
            cleaned = str(account or "").strip()
            if cleaned:
                unique.setdefault(cleaned.casefold(), cleaned)
        return sorted(unique.values(), key=str.casefold)

    def load_directory_accounts(self) -> list[str]:
        """Load the shared cache of selectable AD/Entra account names."""
        try:
            data = json.loads(self.directory_users_path.read_text(encoding="utf-8"))
            accounts = data.get("accounts", [])
            if not isinstance(accounts, list):
                return []
            result = self._normalise_accounts(accounts)
        except (OSError, ValueError, TypeError):
            result = []
        self._directory_users_signature = self._signature(self.directory_users_path)
        return result

    def save_directory_accounts(self, accounts: list[str]) -> list[str]:
        """Merge discovered/manual accounts into the shared selectable-user cache."""
        existing = self.load_directory_accounts()
        merged = self._normalise_accounts(existing + accounts)
        self._write_json(self.directory_users_path, {"version": 1, "accounts": merged})
        self._directory_users_signature = self._signature(self.directory_users_path)
        return merged

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
            user = self._load_preferences(fallback_user)
            self._remember_signatures()
            return fallback_workstations, user, []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            user = self._load_preferences(fallback_user, data)
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
            reservations = [Reservation.from_dict(item) for item in data.get("reservations", [])]
            if removed_legacy_placeholders:
                self.save(workstations, user, reservations, theme_mode=self.theme_mode)
            else:
                self._set_baseline(data)
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
            "version": 4,
            "workstations": [ws.to_schema().model_dump(mode="json") for ws in workstations],
            "reservations": [reservation.to_dict() for reservation in reservations],
        }
        if self._signature(self.path) != self._state_signature and self.path.exists():
            try:
                remote_data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError) as exc:
                raise StoreConflictError("Die gemeinsame Konfigurationsdatei kann nicht sicher zusammengeführt werden.") from exc
            data = self._merge_shared_data(remote_data, data)
        self._write_json(self.path, data)
        self._save_preferences(user, theme_mode)
        self._set_baseline(data)
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
        target_directory_users = target_directory / "portal-directory-users.json"
        if target_directory == self.directory:
            self._save_directory_config()
            return
        pairs = [
            (source, target)
            for source, target in (
                (self.path, target_state),
                (self.events_path, target_events),
                (self.directory_users_path, target_directory_users),
            )
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
        self.directory_users_path = target_directory_users
        self._remember_signatures()


__all__ = ["LocalStore"]
