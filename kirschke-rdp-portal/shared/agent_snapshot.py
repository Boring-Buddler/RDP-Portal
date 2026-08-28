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

SNAPSHOT_VERSION = 1


def get_agent_snapshot_directory() -> Path:
    configured = os.environ.get("AGENT_STATUS_DIR")
    if configured:
        return Path(configured)
    local_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.cwd())
    return Path(local_data) / "KirschkeRDPPortal" / "agent-status"


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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentSnapshot:
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
        )

    def age_seconds(self, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - self.observed_at_utc.astimezone(timezone.utc)).total_seconds())


def _safe_snapshot_name(workstation_id: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", workstation_id).strip("._")
    return safe_name or "workstation"


def write_agent_snapshot(snapshot: AgentSnapshot, directory: Path | None = None) -> Path:
    target_directory = directory or get_agent_snapshot_directory()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / f"{_safe_snapshot_name(snapshot.workstation_id)}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def load_agent_snapshots(directory: Path | None = None) -> list[AgentSnapshot]:
    target_directory = directory or get_agent_snapshot_directory()
    if not target_directory.exists():
        return []
    snapshots: list[AgentSnapshot] = []
    for path in target_directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            snapshots.append(AgentSnapshot.from_dict(data))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return snapshots


__all__ = [
    "AgentSnapshot",
    "get_agent_snapshot_directory",
    "load_agent_snapshots",
    "write_agent_snapshot",
]
