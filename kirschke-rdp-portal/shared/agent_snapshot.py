"""Small local status bridge used to test the Windows agent without Microsoft Graph."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.enums import AgentStatus, SessionState
from shared.file_io import write_json_atomic
from shared.agent_paths import default_agent_directory, expand_directory

SNAPSHOT_VERSION = 1


def get_agent_snapshot_directory() -> Path:
    configured = os.environ.get("AGENT_STATUS_DIR")
    if configured:
        return expand_directory(configured)
    return default_agent_directory()


@dataclass
class AgentSnapshot:
    workstation_id: str
    hostname: str
    agent_version: str
    observed_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    agent_status: AgentStatus = AgentStatus.ONLINE
    current_session_state: SessionState = SessionState.NONE
    current_session_user: str | None = None
    current_windows_session_id: int | None = None
    rdp_sessions: list[dict[str, Any]] = field(default_factory=list)
    session_history: list[dict[str, Any]] = field(default_factory=list)
    version: int = SNAPSHOT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "workstation_id": self.workstation_id,
            "hostname": self.hostname,
            "agent_version": self.agent_version,
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "agent_status": self.agent_status.value,
            "current_session_state": self.current_session_state.value,
            "current_session_user": self.current_session_user,
            "current_windows_session_id": self.current_windows_session_id,
            "rdp_sessions": self.rdp_sessions,
            "session_history": self.session_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSnapshot:
        if not isinstance(data, dict) or data.get("version", SNAPSHOT_VERSION) != SNAPSHOT_VERSION:
            raise ValueError("Unsupported agent snapshot format")
        for key in ("workstation_id", "hostname", "observed_at_utc"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Invalid snapshot field: {key}")
        for key in ("agent_version", "current_session_user"):
            if data.get(key) is not None and not isinstance(data[key], str):
                raise ValueError(f"Invalid snapshot field: {key}")
        session_id = data.get("current_windows_session_id")
        if session_id is not None and (type(session_id) is not int or session_id < 0):
            raise ValueError("Invalid Windows session ID")
        sessions = data.get("rdp_sessions", [])
        history = data.get("session_history", [])
        if not isinstance(history, list) or any(not isinstance(item, dict) for item in history):
            raise ValueError("Invalid session history")
        if not isinstance(sessions, list) or any(not isinstance(item, dict) for item in sessions):
            raise ValueError("Invalid RDP session list")
        for item in sessions:
            for key in ("username", "domain", "full_username", "login_time"):
                if item.get(key) is not None and not isinstance(item[key], str):
                    raise ValueError(f"Invalid RDP session field: {key}")
            if item.get("session_id") is not None and (type(item["session_id"]) is not int or item["session_id"] < 0):
                raise ValueError("Invalid RDP session ID")
            if "session_state" in item:
                SessionState(item["session_state"])
        observed_at = datetime.fromisoformat(str(data["observed_at_utc"]))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        return cls(
            version=int(data.get("version", SNAPSHOT_VERSION)),
            workstation_id=str(data["workstation_id"]),
            hostname=str(data["hostname"]),
            agent_version=str(data.get("agent_version", "")),
            observed_at_utc=observed_at,
            agent_status=AgentStatus(data.get("agent_status", AgentStatus.ONLINE.value)),
            current_session_state=SessionState(
                data.get("current_session_state", SessionState.NONE.value)
            ),
            current_session_user=data.get("current_session_user"),
            current_windows_session_id=data.get("current_windows_session_id"),
            rdp_sessions=list(data.get("rdp_sessions", [])),
            session_history=history[-200:],
        )

    def age_seconds(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - self.observed_at_utc.astimezone(timezone.utc)).total_seconds())


def _safe_snapshot_name(workstation_id: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", workstation_id).strip("._")
    return safe_name or "workstation"


def write_agent_snapshot(snapshot: AgentSnapshot, directory: Path | None = None) -> Path:
    target_directory = expand_directory(directory) if directory is not None else get_agent_snapshot_directory()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / f"{_safe_snapshot_name(snapshot.workstation_id)}.json"
    write_json_atomic(target, snapshot.to_dict())
    return target


@dataclass
class SnapshotFileResult:
    path: Path
    snapshot: AgentSnapshot | None = None
    modified_at: datetime | None = None
    error: str | None = None


def scan_agent_snapshots(directory: Path) -> tuple[list[SnapshotFileResult], list[str]]:
    """Enumerate explicitly so filesystem errors cannot look like an empty folder."""
    target_directory = expand_directory(directory)
    entries = sorted(target_directory.iterdir(), key=lambda p: p.name.casefold())
    files: list[SnapshotFileResult] = []
    other_names: list[str] = []
    for path in entries:
        if path.name.casefold() in {"portal-state.json", "portal-preferences.json", "portal-directory-users.json", "storage-location.json", "storage-config.json", "agent-config.json"}:
            other_names.append(path.name + " (Konfiguration, kein Agent-Status)")
            continue  # An older installation may store inventory beside snapshots.
        if path.suffix.casefold() != ".json":
            other_names.append(path.name)
            continue
        result = SnapshotFileResult(path)
        files.append(result)
        try:
            result.modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            # json.loads(bytes) also recognizes BOM-marked UTF-16 files produced
            # by Windows PowerShell, while retaining strict schema validation.
            result.snapshot = AgentSnapshot.from_dict(json.loads(path.read_bytes()))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.error = str(exc)
    return files, other_names


def load_agent_snapshots(directory: Path | None = None, *, errors: list[str] | None = None) -> list[AgentSnapshot]:
    target_directory = expand_directory(directory) if directory is not None else get_agent_snapshot_directory()
    try:
        files, _ = scan_agent_snapshots(target_directory)
    except FileNotFoundError:
        if errors is not None:
            errors.append("Statusordner ist nicht vorhanden oder nicht erreichbar.")
        return []
    if errors is not None:
        errors.extend(f"{result.path.name}: {result.error}" for result in files if result.error)
    return [result.snapshot for result in files if result.snapshot is not None]


__all__ = [
    "AgentSnapshot",
    "get_agent_snapshot_directory",
    "load_agent_snapshots",
    "write_agent_snapshot",
]
