"""JSON-Ablage des Portals: eigener Stand lokal, gemeinsamer Stand auf einer Freigabe.

Gemeinsame Daten laufen ausschließlich über das Netzwerk. Ohne Eintrag führt
jedes Portal sein Inventar für sich (``state`` neben der EXE). Mit einem
eingetragenen gemeinsamen Inventar liegen Maschinen, Reservierungen, die
Kontoliste und -- ohne eigenen Protokollordner -- auch das Ereignisprotokoll
auf einer SMB-Freigabe, die alle Portale direkt lesen und schreiben.
OneDrive- und SharePoint-Ordner werden an jeder Stelle abgelehnt, siehe
:mod:`shared.sync_guard`.

Mehrere Portale schreiben dabei nie gegeneinander: Jeder Schreibvorgang hält
eine Byte-Sperre auf der Freigabe, liest den aktuellen Stand, führt ihn per
Drei-Wege-Abgleich mit den eigenen Änderungen zusammen und ersetzt die Datei
atomar. Haben zwei Portale *denselben* Eintrag geändert, wird der zweite
Schreibvorgang abgelehnt statt eine Fassung still zu überschreiben.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from pathlib import Path

from portal_app.models.reservation import Reservation
from portal_app.models.session import SessionEvent
from portal_app.models.user import MockUser
from portal_app.models.workstation import Workstation
from shared.agent_paths import (
    default_portal_directory,
    expand_directory,
    is_network_location,
    local_app_directory,
    portable_directory,
    resolve_agent_directory,
)
from shared.file_io import file_lock, write_json_atomic
from shared.schemas import SessionEventSchema, WorkstationSchema
from shared.sync_guard import ensure_not_synced, synced_folder_reason

logger = logging.getLogger(__name__)

STATE_FILE = "portal-state.json"
DIRECTORY_USERS_FILE = "portal-directory-users.json"
EVENTS_FILE = "portal-events.jsonl"
#: Lokale Kopie des zuletzt gelesenen gemeinsamen Inventars. Damit startet das
#: Portal, wenn die Freigabe nicht erreichbar ist -- ohne sie anzufassen.
INVENTORY_CACHE_FILE = "inventar-zuletzt-gelesen.json"

#: Rotate the append-only event log once it passes this size.
EVENT_LOG_MAX_BYTES = 4_000_000
#: Events kept in the live log after a rotation.
EVENT_LOG_KEEP_LINES = 5_000
#: Upper bound on what one load_events() call parses.
EVENT_LOG_MAX_LINES = 20_000


class StoreConflictError(RuntimeError):
    """Raised when two portal instances changed the same shared record."""


class StoreReadError(OSError):
    """Existing state cannot be read safely; never replace it with defaults."""


class LocalStore:
    """Eigener Stand lokal oder gemeinsames Inventar auf einer Netzwerkfreigabe."""

    def __init__(self, path: Path | None = None) -> None:
        self.config_path = self._config_path()
        self._uses_default_location = path is None
        # Ein Hinweis fürs Fenster, wenn ein eingetragener Ordner verworfen
        # wurde -- etwa weil er in OneDrive liegt.
        self.configuration_notice = ""
        # Fest beim Erzeugen bestimmt, und vor dem Speicherort, weil der aus der
        # Einstellung folgt: Beide Dateien gehören zu diesem PC und dürfen nicht
        # mitwandern, wenn der Stand auf eine Freigabe umzieht.
        if path is None:
            self._agent_config_path = self.config_path
            self._inventory_cache_path = self.config_path.parent / INVENTORY_CACHE_FILE
            path = self._configured_directory() / STATE_FILE
        else:
            self._agent_config_path = path.with_name(f"{path.stem}-storage-config.json")
            self._inventory_cache_path = path.with_name(f"{path.stem}-{INVENTORY_CACHE_FILE}")
        self.path = path
        self.directory_users_path = self.path.parent / DIRECTORY_USERS_FILE
        self.preferences_path = (
            self.config_path.parent / "portal-preferences.json"
            if self._uses_default_location
            else self.path.with_name(f"{self.path.stem}-preferences.json")
        )
        self.theme_mode = "system"
        self.status_refresh_interval = 5
        self.selected_login_accounts: dict[str, str] = {}
        self.preferred_login_accounts: dict[str, str] = {}
        self.favorite_workstations: list[str] = []
        self.machine_view = "cards"
        # Die selbst gelegte Reihenfolge der Karten. Leer heisst "nach Zustand
        # sortieren" -- siehe save_machine_order.
        self.machine_order: list[str] = []
        self._state_signature: tuple[int, int] | None = None
        self._events_signature: tuple[int, int] | None = None
        self._directory_users_signature: tuple[int, int] | None = None
        self._baseline_workstations: dict[str, dict] = {}
        self._baseline_reservations: dict[str, dict] = {}

    @staticmethod
    def default_directory() -> Path:
        return default_portal_directory()

    @staticmethod
    def local_directory() -> Path:
        """Der Notausgang auf diesem PC, wenn der eingestellte Ort nicht geht.

        %LOCALAPPDATA% ist immer eine lokale Platte und wird von OneDrive nie
        synchronisiert -- genau darum geht es. Ein Ausweichort, der selbst
        unerreichbar sein kann, verschöbe das Problem nur.
        """
        return local_app_directory() / "lokal"

    @property
    def inventory_cache_path(self) -> Path:
        """Lokale Kopie des zuletzt gelesenen gemeinsamen Inventars."""
        return self._inventory_cache_path

    def use_local_fallback(self) -> Path:
        """Move this store to the local directory and return where it now writes.

        Deliberately not silent for the caller: machines and reservations stop
        being shared with the other portals until the location is corrected, and
        that has to be said rather than discovered.

        Ist ein gemeinsames Inventar eingetragen, beginnt der Notbetrieb mit dem
        zuletzt von dort gelesenen Stand, damit die Maschinen nicht plötzlich
        fehlen. Zurückgeschrieben wird davon nie etwas: Die Freigabe bleibt
        unberührt, bis das Portal sie beim nächsten Start wieder erreicht.
        """
        directory = self.local_directory()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / STATE_FILE
        self.directory_users_path = self.path.parent / DIRECTORY_USERS_FILE
        if self.inventory_directory is not None and self.inventory_cache_path.is_file():
            shutil.copyfile(self.inventory_cache_path, self.path)
        self._state_signature = None
        self._events_signature = None
        self._directory_users_signature = None
        self._baseline_workstations = {}
        self._baseline_reservations = {}
        return directory

    @staticmethod
    def _config_path() -> Path:
        local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
        return Path(local_data) / "KirschkeRDPPortal" / "storage-config.json"

    def _configured_directory(self) -> Path:
        """Das eingetragene gemeinsame Inventar, sonst der eigene Stand neben der EXE.

        Der frühere Eintrag ``storage_directory`` wird bewusst nicht mehr
        gelesen: Er zeigte in der Regel in einen SharePoint-Ordner.
        """
        try:
            configured = self.inventory_directory
        except (OSError, ValueError) as exc:
            # Eine unlesbare Einstellung darf den Start nicht verhindern.
            logger.warning("Speichereinstellung nicht lesbar: %s", exc)
            configured = None
        return configured if configured is not None else self.default_directory()

    def _configured_path(self, key: str, purpose: str) -> Path | None:
        """Einen eingetragenen Ordner lesen und einen synchronisierten verwerfen."""
        configured = self._read_directory_config().get(key)
        if not isinstance(configured, str) or not configured.strip():
            return None
        directory = expand_directory(configured)
        reason = synced_folder_reason(directory)
        if reason:
            logger.warning("%s %s wird ignoriert: %s", purpose, directory, reason)
            self.configuration_notice = (
                f"{purpose} war auf einen OneDrive- oder SharePoint-Ordner eingestellt "
                f"und wird nicht verwendet:\n{directory}\n({reason})\n\n"
                "Bitte im Adminbereich eine Netzwerkfreigabe eintragen."
            )
            return None
        return directory

    @staticmethod
    def _validated_directory(directory: str | Path, purpose: str, *, network_only: bool) -> Path:
        target = expand_directory(directory)
        if not target.is_absolute() or re.search(r"%[^%]+%", str(target)):
            raise ValueError(
                "Bitte einen vollständigen Netzwerkpfad angeben."
                if network_only
                else "Bitte einen vollständigen lokalen oder Netzwerkpfad angeben."
            )
        if network_only and not is_network_location(target):
            raise ValueError(
                f"{purpose} muss auf einer Netzwerkfreigabe liegen, z. B. "
                "\\\\SERVER\\RDP-Portal. Ein lokaler Ordner wäre nur auf diesem PC sichtbar."
            )
        ensure_not_synced(target, purpose)
        return target

    @property
    def inventory_directory(self) -> Path | None:
        """Der eingetragene Ordner des gemeinsamen Inventars, oder ``None``."""
        return self._configured_path("inventory_directory", "Das gemeinsame Inventar")

    @property
    def uses_shared_inventory(self) -> bool:
        inventory = self.inventory_directory
        return inventory is not None and self.path.parent == inventory

    def use_shared_inventory(self, directory: str | Path) -> bool:
        """Auf das gemeinsame Inventar in ``directory`` umstellen.

        Liegt dort schon ein Inventar, gilt es, und der eigene Stand bleibt
        unverändert liegen. Sonst wird der eigene Stand dorthin kopiert -- unter
        der Sperre, damit zwei Portale, die gleichzeitig einrichten, nicht
        beide ihren Stand hineinschreiben. Gibt zurück, ob ein vorhandenes
        Inventar übernommen wurde.
        """
        target = self._validated_directory(directory, "Das gemeinsame Inventar", network_only=True)
        target.mkdir(parents=True, exist_ok=True)
        target_state = target / STATE_FILE
        with file_lock(target_state.with_suffix(".lock")):
            adopted = target_state.exists()
            if adopted:
                self._read_state(target_state)
            else:
                pairs = [(self.path, target_state),
                         (self.directory_users_path, target / DIRECTORY_USERS_FILE)]
                if self.event_log_directory is None:
                    pairs.append((self.events_path, target / EVENTS_FILE))
                for source, destination in pairs:
                    if source.is_file() and not destination.exists():
                        shutil.copy2(source, destination)
                        if destination.suffix == ".json":
                            json.loads(destination.read_text(encoding="utf-8"))
                if not target_state.exists():
                    write_json_atomic(target_state, {"version": 4, "workstations": [], "reservations": []})
            config = self._read_directory_config()
            config["inventory_directory"] = portable_directory(target)
            write_json_atomic(self.agent_config_path, config)
        self._switch_to(target)
        return adopted

    def use_local_inventory(self) -> Path:
        """Das gemeinsame Inventar verlassen und wieder den eigenen Stand führen.

        Der aktuelle gemeinsame Stand wird als eigener übernommen, damit keine
        Maschine verschwindet; der bisherige eigene Stand bleibt als
        ``portal-state.vorher.json`` daneben liegen. Die Freigabe selbst wird
        nicht verändert.
        """
        local = self.default_directory()
        local.mkdir(parents=True, exist_ok=True)
        local_state = local / STATE_FILE
        if self.uses_shared_inventory and self.path.is_file():
            data = self._read_state(self.path)
            if local_state.exists():
                shutil.copy2(local_state, local / "portal-state.vorher.json")
            write_json_atomic(local_state, data)
            if self.directory_users_path.is_file():
                shutil.copy2(self.directory_users_path, local / DIRECTORY_USERS_FILE)
        config = self._read_directory_config()
        config.pop("inventory_directory", None)
        write_json_atomic(self.agent_config_path, config)
        self._switch_to(local)
        return local

    def _switch_to(self, directory: Path) -> None:
        self.path = directory / STATE_FILE
        self.directory_users_path = directory / DIRECTORY_USERS_FILE
        self._state_signature = None
        self._events_signature = None
        self._directory_users_signature = None
        self._baseline_workstations = {}
        self._baseline_reservations = {}

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def agent_config_path(self) -> Path:
        return self._agent_config_path

    def _read_directory_config(self) -> dict:
        try:
            data = json.loads(self.agent_config_path.read_text(encoding="utf-8-sig"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}

    @property
    def event_log_directory(self) -> Path | None:
        """Der eingetragene gemeinsame Protokollordner, oder ``None``.

        Wie die Agentenordner eine Einstellung dieses PCs: Der Pfad selbst ist
        gemeinsam, aber jedes Portal muss ihn für sich kennen und erreichen.
        Ein Eintrag, der in OneDrive oder SharePoint zeigt, wird verworfen.
        """
        return self._configured_path("event_log_directory", "Der Protokollordner")

    @property
    def events_path(self) -> Path:
        """Wo das Ereignisprotokoll liegt.

        Ohne eigenen Protokollordner neben dem Stand -- beim gemeinsamen
        Inventar also ebenfalls auf der Freigabe. Ein eingetragener Ordner ist
        der Weg zu einem gemeinsamen Protokoll, ohne den übrigen Stand zu teilen.
        """
        directory = self.event_log_directory
        return (directory or self.path.parent) / EVENTS_FILE

    def set_event_log_directory(self, directory: str | Path | None) -> Path | None:
        """Den gemeinsamen Protokollordner eintragen oder mit ``None`` entfernen."""
        if directory is None or not str(directory).strip():
            config = self._read_directory_config()
            config.pop("event_log_directory", None)
            write_json_atomic(self.agent_config_path, config)
            self._events_signature = None
            return None
        target = self._validated_directory(directory, "Der Protokollordner", network_only=False)
        config = self._read_directory_config()
        config["event_log_directory"] = portable_directory(target)
        write_json_atomic(self.agent_config_path, config)
        # Der alte Stand gilt nicht mehr: Die naechste Pruefung soll das
        # Protokoll am neuen Ort frisch einlesen, nicht mit der Groesse des
        # alten vergleichen.
        self._events_signature = None
        return target

    @property
    def agent_status_directory(self) -> Path:
        configured = self._read_directory_config().get("agent_status_directory")
        return expand_directory(configured) if configured else resolve_agent_directory(self.directory)

    @property
    def workstation_agent_status_directories(self) -> dict[str, Path]:
        """Return client-local, per-machine fallback folders."""
        configured = self._read_directory_config().get("workstation_agent_status_directories", {})
        if not isinstance(configured, dict):
            return {}
        result: dict[str, Path] = {}
        for workstation_id, directory in configured.items():
            if isinstance(workstation_id, str) and isinstance(directory, str) and directory.strip():
                result[workstation_id.casefold()] = expand_directory(directory)
        return result

    def get_workstation_agent_status_directory(self, workstation_id: str) -> tuple[Path, bool]:
        """Return a machine folder and whether it was explicitly configured."""
        configured = self.workstation_agent_status_directories
        key = workstation_id.strip().casefold()
        if key in configured:
            return configured[key], True
        # Upgrade compatibility: the former global folder remains the default
        # until each existing machine receives its own fallback path.
        return self.agent_status_directory, False

    def set_workstation_agent_status_directory(
        self,
        workstation_id: str,
        directory: str | Path,
    ) -> Path:
        key = workstation_id.strip().casefold()
        if not key:
            raise ValueError("Die Maschinen-ID fehlt.")
        target = self._validated_directory(directory, "Der Fallbackordner", network_only=False)
        config = self._read_directory_config()
        configured = config.get("workstation_agent_status_directories", {})
        configured = dict(configured) if isinstance(configured, dict) else {}
        configured[key] = portable_directory(target)
        config["workstation_agent_status_directories"] = configured
        config["version"] = 2
        write_json_atomic(self.agent_config_path, config)
        return target

    def set_agent_status_directory(self, directory: str | Path) -> Path:
        target = self._validated_directory(directory, "Der Agentenordner", network_only=False)
        config = self._read_directory_config()
        config["agent_status_directory"] = portable_directory(target)
        config["version"] = 1
        write_json_atomic(self.agent_config_path, config)
        return target

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
        write_json_atomic(path, data)

    @staticmethod
    def _read_state(path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or data.get("version", 1) not in {1, 2, 3, 4}:
                raise ValueError("Unbekanntes Speicherformat")
            for field, identifier in (("workstations", "workstation_id"), ("reservations", "reservation_id")):
                records = data.get(field, [])
                if not isinstance(records, list):
                    raise ValueError(f"Ungültige Liste: {field}")
                seen = set()
                for item in records:
                    if not isinstance(item, dict) or not isinstance(item.get(identifier), str) or not item[identifier].strip():
                        raise ValueError(f"Ungültige ID: {field}")
                    key = item[identifier].casefold()
                    if key in seen:
                        raise ValueError(f"Doppelte ID: {item[identifier]}")
                    seen.add(key)
                    if field == "workstations":
                        WorkstationSchema.model_validate(item)
                    else:
                        Reservation.from_dict(item)
            return data
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StoreReadError(f"Speicherdatei kann nicht sicher gelesen werden: {path}. {exc}") from exc

    @staticmethod
    def _user_from_data(data: dict, fallback: MockUser) -> MockUser:
        if not isinstance(data, dict):
            return fallback
        own_accounts = LocalStore._normalise_accounts(data.get("own_accounts", []))
        own = {name.casefold() for name in own_accounts}
        # Nur, was auch unter den eigenen Konten steht: Eine Markierung ohne
        # Konto bewirkt nichts und tauchte sonst nach dem Entfernen wieder auf.
        shared_accounts = [
            name
            for name in LocalStore._normalise_accounts(data.get("shared_accounts", []))
            if name.casefold() in own
        ]
        return MockUser(
            object_id=data.get("object_id", fallback.object_id),
            upn=data.get("upn", fallback.upn),
            display_name=data.get("display_name", fallback.display_name),
            email=data.get("email", fallback.email),
            role=fallback.role,
            rdp_username=data.get("rdp_username"),
            rdp_domain=data.get("rdp_domain"),
            windows_identity=fallback.windows_identity,
            windows_sid=fallback.windows_sid,
            own_accounts=own_accounts,
            shared_accounts=shared_accounts,
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
            # The process identity and its SID are detected at startup and stay
            # unpersisted on purpose; these claimed extra accounts are the one part
            # of the identity picture the person maintains themselves.
            "own_accounts": list(user.own_accounts),
            "shared_accounts": list(user.shared_accounts),
        }

    def _load_preferences(self, fallback: MockUser, legacy_data: dict | None = None) -> MockUser:
        data: dict = {}
        uses_legacy_data = False
        try:
            data = json.loads(self.preferences_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, AttributeError):
            data = legacy_data or {}
            uses_legacy_data = bool(legacy_data)
        if not isinstance(data, dict):
            data = {}
        stored_theme = data.get("theme_mode")
        stored_interval = data.get("status_refresh_interval", 5)
        self.status_refresh_interval = (
            max(2, min(60, stored_interval))
            if type(stored_interval) is int
            else 5
        )
        order = data.get("machine_order", [])
        self.machine_order = (
            [value.strip() for value in order if isinstance(value, str) and value.strip()]
            if isinstance(order, list)
            else []
        )
        choices = data.get("selected_login_accounts", {})
        self.selected_login_accounts = {
            key: value for key, value in choices.items()
            if isinstance(key, str) and isinstance(value, str)
        } if isinstance(choices, dict) else {}
        preferred = data.get("preferred_login_accounts", {})
        self.preferred_login_accounts = {
            key: value for key, value in preferred.items()
            if isinstance(key, str) and isinstance(value, str)
        } if isinstance(preferred, dict) else {}
        favorites = data.get("favorite_workstations", [])
        self.favorite_workstations = [
            value for value in favorites if isinstance(value, str) and value.strip()
        ] if isinstance(favorites, list) else []
        self.machine_view = "list" if data.get("machine_view") == "list" else "cards"
        if uses_legacy_data and data.get("version", 0) < 3:
            self.theme_mode = "dark" if stored_theme == "dark" else "system"
        else:
            self.theme_mode = stored_theme if stored_theme in {"system", "light", "dark"} else "system"
        return self._user_from_data(data.get("user", {}), fallback)

    def _save_preferences(self, user: MockUser, theme_mode: str) -> None:
        self.theme_mode = theme_mode if theme_mode in {"system", "light", "dark"} else "system"
        self._write_json(
            self.preferences_path,
            {"version": 2, "theme_mode": self.theme_mode, "user": self._user_data(user),
             "selected_login_accounts": self.selected_login_accounts,
             "preferred_login_accounts": self.preferred_login_accounts,
             "favorite_workstations": self.favorite_workstations,
             "machine_view": self.machine_view,
             "machine_order": self.machine_order,
             "status_refresh_interval": self.status_refresh_interval},
        )

    def save_machine_order(self, order: list[str], user: MockUser) -> list[str]:
        """Die selbst gelegte Reihenfolge der Maschinenkarten merken.

        Gehört in die Benutzerdatei und nicht in den gemeinsamen Stand: Sie ist
        eine Angewohnheit, keine Eigenschaft der Maschinen. Würde sie geteilt,
        legte der Letzte, der eine Karte verschiebt, die Anordnung für alle fest.

        Eine leere Liste bedeutet "keine eigene Reihenfolge" und stellt damit die
        Sortierung nach Zustand wieder her.
        """
        previous = list(self.machine_order)
        seen: dict[str, str] = {}
        for value in order:
            if isinstance(value, str) and value.strip():
                seen.setdefault(value.strip().casefold(), value.strip())
        self.machine_order = list(seen.values())
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.machine_order = previous
            raise
        return list(self.machine_order)

    def save_status_refresh_interval(self, seconds: int, user: MockUser) -> int:
        if type(seconds) is not int or not 2 <= seconds <= 60:
            raise ValueError("Das Statusintervall muss zwischen 2 und 60 Sekunden liegen.")
        previous = self.status_refresh_interval
        self.status_refresh_interval = seconds
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.status_refresh_interval = previous
            raise
        return seconds

    def save_login_selection(self, workstation_id: str, account: str, user: MockUser) -> None:
        from shared.login_accounts import validate_login_account
        previous = dict(self.selected_login_accounts)
        if account:
            self.selected_login_accounts[workstation_id] = validate_login_account(account)
        else:
            self.selected_login_accounts.pop(workstation_id, None)
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.selected_login_accounts = previous
            raise

    def save_favorite(self, workstation_id: str, favorite: bool, user: MockUser) -> None:
        previous = list(self.favorite_workstations)
        favorites = {value.casefold(): value for value in previous}
        key = workstation_id.strip().casefold()
        if favorite:
            favorites[key] = workstation_id.strip()
        else:
            favorites.pop(key, None)
        self.favorite_workstations = list(favorites.values())
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.favorite_workstations = previous
            raise

    def save_preferred_login_account(
        self, workstation_id: str, account: str | None, user: MockUser
    ) -> None:
        from shared.login_accounts import validate_login_account

        previous = dict(self.preferred_login_accounts)
        if account is None:
            self.preferred_login_accounts.pop(workstation_id, None)
        else:
            self.preferred_login_accounts[workstation_id] = (
                validate_login_account(account) if account else ""
            )
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.preferred_login_accounts = previous
            raise

    def save_machine_view(self, view: str, user: MockUser) -> None:
        if view not in {"cards", "list"}:
            raise ValueError("Unbekannte Maschinenansicht")
        previous = self.machine_view
        self.machine_view = view
        try:
            self._save_preferences(user, self.theme_mode)
        except OSError:
            self.machine_view = previous
            raise

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
        """Whether the shared machine state changed since the last read/write.

        Das Ereignisprotokoll steht hier bewusst nicht mehr mit drin. Liegt es
        in einem gemeinsamen Ordner, schreibt jeder Kollege staendig hinein --
        und jeder dieser Eintraege haette einen vollstaendigen Neuaufbau des
        Inventars ausgeloest, samt erneutem Parsen des gesamten Protokolls.
        Siehe :meth:`has_new_events`.
        """
        return (
            self._signature(self.path) != self._state_signature
            or self._signature(self.directory_users_path) != self._directory_users_signature
        )

    def has_new_events(self) -> bool:
        """Whether the event log changed since it was last read."""
        return self._signature(self.events_path) != self._events_signature

    def change_probe_paths(self) -> tuple[Path, Path, Path]:
        """Die Dateien, deren Signaturen :meth:`changes_from` erwartet.

        Auf einer Freigabe kann schon ein ``stat`` hängen. Die Signaturen
        werden deshalb im Hintergrund ermittelt (:func:`file_signatures`) und
        hier nur noch verglichen.
        """
        return self.path, self.directory_users_path, self.events_path

    def changes_from(
        self,
        paths: tuple[Path, Path, Path],
        signatures: tuple[tuple[int, int] | None, ...],
    ) -> tuple[bool, bool]:
        """(Inventar geändert, Protokoll geändert) aus vorab ermittelten Signaturen.

        Gehört die Messung zu Pfaden, die inzwischen nicht mehr gelten, sagt
        sie nichts und zählt als "unverändert".
        """
        if paths != self.change_probe_paths():
            return False, False
        state, users, events = signatures
        return (
            state != self._state_signature or users != self._directory_users_signature,
            events != self._events_signature,
        )

    def _remember_inventory(self, data: dict) -> None:
        """Den gemeinsamen Stand lokal festhalten, für einen Start ohne Freigabe."""
        try:
            write_json_atomic(self.inventory_cache_path, data)
        except OSError as exc:
            logger.warning("Lokale Kopie des Inventars nicht geschrieben: %s", exc)

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
        except (OSError, ValueError, TypeError, AttributeError):
            result = []
        self._directory_users_signature = self._signature(self.directory_users_path)
        return result

    def save_directory_accounts(self, accounts: list[str]) -> list[str]:
        """Merge discovered/manual accounts into the shared selectable-user cache.

        Unter der Sperre gelesen und geschrieben: Liegt die Liste auf der
        gemeinsamen Freigabe, ginge sonst ein Konto verloren, das ein anderes
        Portal im selben Augenblick ergänzt.
        """
        with file_lock(self.directory_users_path.with_suffix(".lock")):
            existing = self.load_directory_accounts()
            merged = self._normalise_accounts(existing + accounts)
            self._write_json(self.directory_users_path, {"version": 1, "accounts": merged})
        self._directory_users_signature = self._signature(self.directory_users_path)
        return merged

    def load(
        self,
        fallback_workstations: list[Workstation],
        fallback_user: MockUser,
        *,
        migrate: bool = True,
    ) -> tuple[list[Workstation], MockUser, list[Reservation]]:
        source = self.path
        shared = self.uses_shared_inventory
        if shared and not source.is_file():
            # Nicht erreichbar oder entfernt -- beides heisst: nichts anlegen.
            # Ein leeres oder veraltetes Inventar auf der Freigabe wuerde bei
            # allen anderen Portalen die Maschinen verschwinden lassen.
            reachable = source.parent.is_dir()
            raise StoreReadError(
                f"Das gemeinsame Inventar {source} "
                + ("fehlt auf der Freigabe." if reachable else "ist nicht erreichbar.")
            )
        if (not source.exists() and self._uses_default_location
                and self._state_signature is None and not self._baseline_workstations
                and not self._baseline_reservations):
            # Ein Stand aus einem frueheren Notbetrieb oder einer portablen EXE
            # in einem Cloud-Ordner -- beide liegen im lokalen Profil.
            for directory in (local_app_directory() / "daten", self.local_directory()):
                previous = directory / STATE_FILE
                if previous != source and previous.is_file():
                    source = previous
                    break
        if not source.exists():
            if self._state_signature is not None or self._baseline_workstations or self._baseline_reservations:
                raise StoreReadError("Die bisherige Speicherdatei fehlt; bitte Verbindung und Speicherort prüfen.")
            user = self._load_preferences(fallback_user)
            self._remember_signatures()
            return fallback_workstations, user, []
        try:
            data = self._read_state(source)
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
                choice = self.selected_login_accounts.get(workstation.workstation_id)
                # Die eigene Wahl gilt ohne weitere Prüfung. Sie vorher gegen
                # login_accounts und username_hint zu halten, hat genau die
                # Wahl weggeworfen, die man über eine gemeldete Sitzung trifft:
                # die steht in session_accounts, und die kennt der Store nicht.
                # Das Ergebnis war ein stiller Rücksprung auf "Standard" bei
                # jedem Neuladen -- und neu geladen wird alle paar Sekunden,
                # sobald ein anderes Portal den gemeinsamen Stand schreibt.
                # Der Kontoname wurde beim Speichern bereits geprüft, und die
                # Auswahlliste zeigt eine nicht mehr gelistete Wahl als
                # "Gewählt · …" an, statt sie verschwinden zu lassen.
                if choice:
                    workstation.selected_login_account = choice
                username_hint = workstation.username_hint or ""
                if re.fullmatch(r"user\d+@prof-kirschke\.de", username_hint, re.IGNORECASE):
                    workstation.username_hint = None
                    removed_legacy_placeholders = True
            reservations = [Reservation.from_dict(item) for item in data.get("reservations", [])]
            self._set_baseline(data)
            self._remember_signatures()
            if shared:
                self._remember_inventory(data)
            if removed_legacy_placeholders and migrate and source == self.path:
                self.save(workstations, user, reservations, theme_mode=self.theme_mode)
            else:
                self._set_baseline(data)
                self._remember_signatures()
            return workstations, user, reservations
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StoreReadError(f"Portaldaten konnten nicht geladen werden: {exc}") from exc

    def read_reservations(self) -> list[Reservation]:
        """Read authoritative bookings without acknowledging other pending edits."""
        return [Reservation.from_dict(item) for item in self._read_state(self.path).get("reservations", [])]

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
        local_data = data
        with file_lock(self.path.with_suffix(".lock")):
            if self.path.exists():
                data = self._merge_shared_data(self._read_state(self.path), local_data)
            elif self._state_signature is not None:
                raise StoreConflictError("Die gemeinsame Speicherdatei wurde entfernt. Bitte den Speicherort prüfen.")
            machine_ids = {item["workstation_id"] for item in data["workstations"]}
            reservations_to_check = [Reservation.from_dict(item) for item in data["reservations"]]
            for index, reservation in enumerate(reservations_to_check):
                if reservation.workstation_id not in machine_ids:
                    raise StoreConflictError("Eine reservierte Maschine wurde zwischenzeitlich gelöscht.")
                if any(
                    previous.workstation_id == reservation.workstation_id
                    and previous.start < reservation.end and previous.end > reservation.start
                    for previous in reservations_to_check[:index]
                ):
                    raise StoreConflictError("Der Reservierungszeitraum wurde zwischenzeitlich belegt.")
            self._write_json(self.path, data)
        if self.uses_shared_inventory:
            self._remember_inventory(data)
        self._save_preferences(user, theme_mode)
        # Only the local input was seen by this caller. Remembering merged remote
        # records here would interpret its next save as deleting unseen records.
        self._set_baseline(local_data)
        self._state_signature = self._signature(self.path) if data == local_data else None

    def load_events(self) -> list[SessionEvent]:
        """Load the append-only portal event log; malformed individual lines are skipped.

        Only the newest ``EVENT_LOG_MAX_LINES`` lines are parsed. The file is
        rotated on append, so this bounds both the read and the Pydantic
        validation regardless of how long the pilot has been running.
        """
        self._events_signature = self._signature(self.events_path)
        if not self.events_path.exists():
            return []
        events: list[SessionEvent] = []
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines[-EVENT_LOG_MAX_LINES:]:
            if not line.strip():
                continue
            try:
                schema = SessionEventSchema.model_validate_json(line)
                events.append(SessionEvent.from_schema(schema))
            except ValueError:
                continue
        return events

    def append_event(self, event: SessionEvent) -> None:
        """Append one portal event without retaining credentials or passwords."""
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = event.to_schema().model_dump_json()
        with file_lock(self.events_path.with_suffix(".lock")):
            with self.events_path.open("a", encoding="utf-8") as event_file:
                event_file.write(serialized + "\n")
            self._rotate_event_log()
        # Do not acknowledge unrelated state changes while appending an event.
        self._events_signature = self._signature(self.events_path)

    def _rotate_event_log(self) -> None:
        """Keep the newest events and move the rest aside. Caller holds the lock.

        Without this the log grew without bound and every read parsed all of it.
        The previous generation is kept as one ``.1`` file so a pilot audit can
        still reach older events.
        """
        try:
            if self.events_path.stat().st_size <= EVENT_LOG_MAX_BYTES:
                return
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= EVENT_LOG_KEEP_LINES:
            return
        archive = self.events_path.with_suffix(self.events_path.suffix + ".1")
        retained = lines[-EVENT_LOG_KEEP_LINES:]
        try:
            # Append the rotated-out events so the archive keeps its history, then
            # replace the live log atomically with what we keep.
            with archive.open("a", encoding="utf-8") as stream:
                stream.write("\n".join(lines[:-EVENT_LOG_KEEP_LINES]) + "\n")
            temporary = self.events_path.with_suffix(self.events_path.suffix + ".tmp")
            temporary.write_text("\n".join(retained) + "\n", encoding="utf-8")
            os.replace(temporary, self.events_path)
        except OSError:
            # A failed rotation must never lose the event that was just written.
            return

    def initialize_event_log(self) -> None:
        """Create the empty append-only log on first portal startup."""
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self._remember_signatures()


def file_signatures(paths: tuple[Path, ...]) -> tuple[tuple[int, int] | None, ...]:
    """Signaturen mehrerer Dateien. Blockiert auf einer langsamen Freigabe."""
    return tuple(LocalStore._signature(path) for path in paths)


__all__ = ["LocalStore", "StoreConflictError", "StoreReadError", "file_signatures"]
