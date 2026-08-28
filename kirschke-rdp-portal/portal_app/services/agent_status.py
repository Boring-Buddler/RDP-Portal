"""Apply local workstation-agent snapshots to the credential-free test portal."""

from __future__ import annotations

from datetime import datetime, timezone

from portal_app.models.workstation import Workstation
from shared.agent_snapshot import AgentSnapshot, get_agent_snapshot_directory, load_agent_snapshots
from shared.enums import AgentStatus


class LocalAgentStatusService:
    """Read the optional local bridge that is replaced by Graph in production."""

    def __init__(self, stale_after_seconds: int = 90, offline_after_seconds: int = 300) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.offline_after_seconds = offline_after_seconds
        self.last_snapshot_count = 0
        self.last_match_count = 0

    @property
    def directory(self):
        return get_agent_snapshot_directory()

    @staticmethod
    def _identity_values(workstation: Workstation) -> set[str]:
        values = {
            workstation.workstation_id,
            workstation.hostname,
            workstation.fqdn or "",
        }
        return {
            identity.casefold()
            for value in values
            if value
            for identity in (value, value.split(".", 1)[0])
        }

    @staticmethod
    def _snapshot_values(snapshot: AgentSnapshot) -> set[str]:
        return {
            identity.casefold()
            for value in (snapshot.workstation_id, snapshot.hostname)
            if value
            for identity in (value, value.split(".", 1)[0])
        }

    def _effective_status(self, snapshot: AgentSnapshot, now: datetime) -> AgentStatus:
        age = snapshot.age_seconds(now)
        if age > self.offline_after_seconds:
            return AgentStatus.OFFLINE
        if age > self.stale_after_seconds:
            return AgentStatus.STALE
        return snapshot.agent_status

    def apply(self, workstations: list[Workstation]) -> int:
        snapshots = load_agent_snapshots()
        self.last_snapshot_count = len(snapshots)
        self.last_match_count = 0
        changed_count = 0
        now = datetime.now(timezone.utc)
        for workstation in workstations:
            identities = self._identity_values(workstation)
            matches = [
                snapshot
                for snapshot in snapshots
                if identities.intersection(self._snapshot_values(snapshot))
            ]
            if not matches:
                continue
            snapshot = max(matches, key=lambda item: item.observed_at_utc)
            before = (
                workstation.agent_status,
                workstation.agent_last_seen_utc,
                workstation.agent_version,
                workstation.current_session_state,
                workstation.current_session_user,
                workstation.current_windows_session_id,
            )
            workstation.agent_status = self._effective_status(snapshot, now)
            workstation.agent_last_seen_utc = snapshot.observed_at_utc
            workstation.agent_version = snapshot.agent_version
            workstation.current_session_state = snapshot.current_session_state
            workstation.current_session_user = snapshot.current_session_user
            workstation.current_windows_session_id = snapshot.current_windows_session_id
            workstation.last_session_event_utc = snapshot.observed_at_utc
            self.last_match_count += 1
            after = (
                workstation.agent_status,
                workstation.agent_last_seen_utc,
                workstation.agent_version,
                workstation.current_session_state,
                workstation.current_session_user,
                workstation.current_windows_session_id,
            )
            if before != after:
                changed_count += 1
        return changed_count


__all__ = ["LocalAgentStatusService"]
