"""Read and explain the full agent-file-to-dashboard status path."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path

from portal_app.models.workstation import Workstation
from portal_app.version import PORTAL_VERSION
from shared.agent_snapshot import AgentSnapshot, get_agent_snapshot_directory, scan_agent_snapshots
from shared.enums import AgentStatus


class LocalAgentStatusService:
    def __init__(self, stale_after_seconds: int = 90, offline_after_seconds: int = 300,
                 directory: Path | None = None) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.offline_after_seconds = offline_after_seconds
        self._directory = directory
        self.last_snapshot_count = 0
        self.last_file_count = 0
        self.last_match_count = 0
        self.last_errors: list[str] = []
        self.last_report = "Noch nicht geprüft"
        self.last_checked_at: datetime | None = None
        self._live_snapshots: dict[str, tuple] = {}
        self._live_failures: dict[str, tuple[datetime, str, tuple]] = {}

    def accept_live_snapshot(self, ws: Workstation, snapshot: AgentSnapshot, elapsed: int) -> None:
        expected_id = (ws.agent_workstation_id or ws.workstation_id).casefold()
        matches = snapshot.workstation_id.casefold() == expected_id
        if not ws.agent_workstation_id:
            matches |= bool(self._identity_values(ws).intersection(self._hostname_values(snapshot.hostname)))
        if not matches:
            raise ValueError(f"Der antwortende Agent ({snapshot.workstation_id}, {snapshot.hostname}) passt nicht zur Maschine. Agent-Zuordnung prüfen.")
        self._live_snapshots[ws.workstation_id] = (
            snapshot,
            datetime.now(timezone.utc),
            elapsed,
            (ws.get_agent_status_target(), ws.agent_workstation_id),
        )
        self._live_failures.pop(ws.workstation_id, None)

    def record_live_failure(self, ws: Workstation, message: str) -> None:
        """Remember a failed request without presenting an older reply as current."""
        try:
            target = (ws.get_agent_status_target(), ws.agent_workstation_id)
        except ValueError:
            target = (None, ws.agent_workstation_id)
        self._live_failures[ws.workstation_id] = (
            datetime.now(timezone.utc),
            message,
            target,
        )

    @property
    def directory(self) -> Path:
        return self._directory or get_agent_snapshot_directory()

    def set_directory(self, directory: Path | None) -> None:
        self._directory = directory

    def directory_for(self, workstation: Workstation) -> Path:
        configured = (workstation.agent_fallback_directory or "").strip()
        return (
            Path(configured)
            if workstation.agent_fallback_is_explicit and configured
            else self.directory
        )

    @property
    def directory_summary(self) -> str:
        return getattr(self, "_directory_summary", str(self.directory))

    @staticmethod
    def _hostname_values(value: str) -> set[str]:
        value = value.strip().rstrip(".").casefold()
        try:
            return {str(ip_address(value))}
        except ValueError:
            pass
        return {value, value.split(".", 1)[0]} if value else set()

    @classmethod
    def _identity_values(cls, workstation: Workstation) -> set[str]:
        return cls._hostname_values(workstation.hostname) | cls._hostname_values(workstation.fqdn or "")

    def _effective_status(self, snapshot: AgentSnapshot, now: datetime) -> AgentStatus:
        if (snapshot.observed_at_utc - now).total_seconds() > 60:
            return AgentStatus.ERROR
        age = snapshot.age_seconds(now)
        if age > self.offline_after_seconds:
            return AgentStatus.OFFLINE
        if age > self.stale_after_seconds:
            return AgentStatus.STALE
        return snapshot.agent_status

    def _status_reason(self, snapshot: AgentSnapshot, now: datetime) -> str:
        delta = (now - snapshot.observed_at_utc).total_seconds()
        if delta < -60:
            return f"Agent-Zeit liegt {int(-delta)} s in der Zukunft; Windows-Uhrzeiten prüfen."
        if delta > self.offline_after_seconds:
            return f"Letzte Agent-Meldung vor {int(delta)} s; Agent-Lauf und Synchronisierung prüfen."
        if delta > self.stale_after_seconds:
            return f"Agent-Meldung {int(delta)} s alt; Status veraltet."
        return f"Aktuelle Meldung ({max(0, int(delta))} s alt); Agent meldet {snapshot.agent_status.value}."

    def _missing_status(self, ws: Workstation, now: datetime) -> None:
        if ws.agent_last_seen_utc is None:
            ws.agent_status = AgentStatus.OFFLINE
            return
        last_seen = ws.agent_last_seen_utc
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age = (now - last_seen).total_seconds()
        if age > self.offline_after_seconds:
            ws.agent_status = AgentStatus.OFFLINE
        elif age > self.stale_after_seconds:
            ws.agent_status = AgentStatus.STALE
        elif age < -60:
            ws.agent_status = AgentStatus.ERROR

    def apply(self, workstations: list[Workstation]) -> int:
        self.last_errors = []
        self.last_match_count = 0
        now = datetime.now(timezone.utc)
        self.last_checked_at = now
        directories: dict[str, Path] = {}
        for ws in workstations:
            directory = self.directory_for(ws)
            directories.setdefault(str(directory).casefold(), directory)
        if not directories:
            directories[str(self.directory).casefold()] = self.directory
        scans: dict[str, tuple[list, list[str], list[str]]] = {}
        all_files = []
        all_other_names: list[str] = []
        for key, directory in directories.items():
            errors: list[str] = []
            try:
                files, other_names = scan_agent_snapshots(directory)
            except OSError as exc:
                files, other_names = [], []
                errors.append(f"{directory}: Ordner kann nicht gelesen werden: {exc}")
            scans[key] = (files, other_names, errors)
            all_files.extend(files)
            all_other_names.extend(other_names)
            self.last_errors.extend(errors)
        self._directory_summary = (
            str(next(iter(directories.values())))
            if len(directories) == 1
            else f"{len(directories)} maschinenspezifische Fallbackordner"
        )
        lines = [
            f"RDP-Portal {PORTAL_VERSION} – Agent-Diagnose",
            f"Prüfung (UTC): {now.isoformat()}",
            f"Fallbackordner: {self.directory_summary}",
            f"Portal-Maschinen: {len(workstations)}",
        ]
        self.last_file_count = len(all_files)
        snapshots = [result.snapshot for result in all_files if result.snapshot is not None]
        self.last_snapshot_count = len(snapshots)
        lines.append(f"JSON-Dateien gefunden: {len(all_files)}; gültige Agent-Meldungen: {len(snapshots)}")
        for key, directory in directories.items():
            files, other_names, errors = scans[key]
            lines.append(f"\nOrdner: {directory}")
            if errors:
                lines.extend(errors)
            for result in files:
                lines.append(f"Datei: {result.path.name}")
                if result.modified_at:
                    lines.append(f"Datei geändert (UTC): {result.modified_at.isoformat()}")
                if result.error:
                    error = f"{result.path}: {result.error}"
                    self.last_errors.append(error)
                    lines.append(error)
                    continue
                snapshot = result.snapshot
                lines.extend([
                    f"Agent-ID: {snapshot.workstation_id}; Hostname: {snapshot.hostname}",
                    f"Meldung (UTC): {snapshot.observed_at_utc.isoformat()}",
                    self._status_reason(snapshot, now),
                    f"Sitzung: {snapshot.current_session_state.value}; Benutzer: {snapshot.current_session_user or '–'}",
                ])
            if other_names:
                lines.append("Weitere Einträge: " + ", ".join(other_names[:20]))
        changed_count = 0
        selected_files: set[Path] = set()
        def agent_id(ws: Workstation) -> str:
            return (ws.agent_workstation_id or ws.workstation_id).strip().casefold()

        for ws in workstations:
            directory = self.directory_for(ws)
            files, _, directory_errors = scans[str(directory).casefold()]
            directory_snapshots = [result.snapshot for result in files if result.snapshot is not None]
            before = (ws.agent_status, ws.agent_last_seen_utc, ws.agent_version,
                      ws.current_session_state, ws.current_session_user,
                      ws.current_windows_session_id, ws.agent_diagnostic, ws.agent_sessions,
                      ws.agent_status_source, ws.agent_live_error)
            exact = [result for result in files if result.snapshot is not None and
                     result.snapshot.workstation_id.strip().casefold() == agent_id(ws)]
            aliases = [result for result in files if result.snapshot is not None and
                       self._identity_values(ws).intersection(self._hostname_values(result.snapshot.hostname)) and
                       not any(other is not ws and agent_id(other) == result.snapshot.workstation_id.strip().casefold()
                               for other in workstations)]
            # A host fallback is only safe if it identifies one portal machine.
            ambiguous = len({item.snapshot.workstation_id.strip().casefold() for item in aliases}) > 1 or any(
                other is not ws and self._identity_values(ws).intersection(self._identity_values(other))
                for other in workstations
            )
            duplicate_id = sum(agent_id(other) == agent_id(ws) for other in workstations) > 1
            matches = [] if duplicate_id else (exact or ([] if ambiguous or ws.agent_workstation_id else aliases))
            if matches:
                selected = max(matches, key=lambda item: item.snapshot.observed_at_utc)
                snapshot = selected.snapshot
                selected_files.add(selected.path)
                ws.agent_status = self._effective_status(snapshot, now)
                ws.agent_last_seen_utc = snapshot.observed_at_utc
                ws.agent_version = snapshot.agent_version
                ws.current_session_state = snapshot.current_session_state
                ws.current_session_user = snapshot.current_session_user
                ws.current_windows_session_id = snapshot.current_windows_session_id
                ws.agent_sessions = snapshot.rdp_sessions
                ws.agent_session_history = snapshot.session_history
                ws.last_session_event_utc = snapshot.observed_at_utc
                ws.agent_status_source = "file"
                method = ("zugeordnete Agent-ID" if ws.agent_workstation_id else "Maschinen-ID") if exact else "Hostname"
                ws.agent_diagnostic = f"{selected.path.name} über {method}: {self._status_reason(snapshot, now)}"
                self.last_match_count += 1
            else:
                self._missing_status(ws, now)
                ws.agent_status_source = "none"
                if duplicate_id:
                    reason = "Agent-ID mehrfach zugeordnet; Zuordnung in den Maschinendetails korrigieren."
                elif directory_errors and not directory_snapshots:
                    reason = "Agent-Dateien nicht lesbar; Agent-Diagnose öffnen."
                elif not directory_snapshots:
                    reason = "Keine gültige Agent-JSON im Fallbackordner dieser Maschine."
                elif aliases and ambiguous:
                    reason = "Hostname nicht eindeutig; Maschinen-ID im Agent-Setup korrigieren."
                else:
                    reason = "JSON gelesen, aber Maschinen-ID und Hostname passen nicht. Details → Agent zuordnen öffnen."
                ws.agent_diagnostic = reason
            failure = self._live_failures.get(ws.workstation_id)
            try:
                current_target = (ws.get_agent_status_target(), ws.agent_workstation_id)
            except ValueError:
                current_target = (None, ws.agent_workstation_id)
            if failure and failure[2] != current_target:
                self._live_failures.pop(ws.workstation_id, None)
                failure = None
            ws.agent_live_error = failure[1] if failure else None
            live = self._live_snapshots.get(ws.workstation_id)
            if live:
                snapshot, received, elapsed, target = live
                try:
                    same_target = target == (
                        ws.get_agent_status_target(),
                        ws.agent_workstation_id,
                    )
                except ValueError:
                    same_target = False
                newer_file = bool(matches and selected.snapshot.observed_at_utc >= snapshot.observed_at_utc)
                if not same_target or newer_file or (now - received).total_seconds() > self.stale_after_seconds:
                    self._live_snapshots.pop(ws.workstation_id, None)
                else:
                    ws.agent_status = self._effective_status(snapshot, now)
                    ws.agent_last_seen_utc = snapshot.observed_at_utc
                    ws.agent_version = snapshot.agent_version
                    ws.current_session_state = snapshot.current_session_state
                    ws.current_session_user = snapshot.current_session_user
                    ws.current_windows_session_id = snapshot.current_windows_session_id
                    ws.agent_sessions = snapshot.rdp_sessions
                    ws.agent_status_source = "live"
                    if failure and failure[0] > received:
                        # The last known live payload stays newer than the file,
                        # but the failed request must not look like fresh reachability.
                        ws.agent_status = AgentStatus.STALE
                        ws.agent_diagnostic = (
                            f"{failure[1]} Letzter Live-Stand von {received.astimezone():%H:%M:%S} "
                            f"({elapsed} ms); {self._status_reason(snapshot, now)}"
                        )
                    else:
                        ws.agent_diagnostic = f"Agent-Live-Abfrage um {received.astimezone():%H:%M:%S} ({elapsed} ms); {self._status_reason(snapshot, now)}"
                    if not matches:
                        self.last_match_count += 1
            if ws.agent_status_source == "file" and failure:
                ws.agent_diagnostic = f"{failure[1]} Datei-Fallback: {ws.agent_diagnostic}"
            elif ws.agent_status_source == "none" and failure:
                ws.agent_diagnostic = f"{failure[1]} {ws.agent_diagnostic}"
            lines.append(f"\nPortal: {ws.display_name}; ID: {ws.workstation_id}; Host: {ws.hostname}; FQDN: {ws.fqdn or '–'}")
            lines.append(f"Erwartete Agent-ID: {ws.agent_workstation_id or ws.workstation_id}")
            lines.append(f"Fallbackordner: {directory}")
            lines.append(ws.agent_diagnostic)
            after = (ws.agent_status, ws.agent_last_seen_utc, ws.agent_version,
                     ws.current_session_state, ws.current_session_user,
                     ws.current_windows_session_id, ws.agent_diagnostic, ws.agent_sessions,
                     ws.agent_status_source, ws.agent_live_error)
            changed_count += before != after
        for result in all_files:
            if result.snapshot is not None and result.path not in selected_files:
                lines.append(f"Nicht übernommen: {result.path.name} (keine eindeutige Zuordnung oder ältere doppelte Meldung).")
        if self.last_errors:
            lines.append("\nLesefehler:\n" + "\n".join(self.last_errors))
        if not workstations:
            lines.append("Keine Portalmaschine angelegt; eine Statusdatei legt keine Maschine automatisch an.")
        lines.append(f"\nZuordnung: {self.last_match_count}/{len(workstations)} Maschinen.")
        self.last_report = "\n".join(lines)
        return changed_count


__all__ = ["LocalAgentStatusService"]
