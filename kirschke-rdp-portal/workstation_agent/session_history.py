"""Bounded, persistent history of observed Windows session transitions."""
from datetime import datetime, timezone
import json
from pathlib import Path

from shared.file_io import write_json_atomic


class SessionHistory:
    def __init__(self, path: Path):
        self.path = path
        self.current: dict[str, dict] = {}
        self.events: list[dict] = []
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            self.current = data["current"]
            self.events = data["events"][-200:]

    def observe(self, sessions: list[dict]) -> None:
        current = {str(s["session_id"]): {key: s.get(key) for key in
                   ("session_id", "username", "domain", "login_time", "session_state")} for s in sessions}
        now = datetime.now(timezone.utc).isoformat()
        events = []
        for key in sorted(set(self.current) | set(current)):
            previous, new = self.current.get(key), current.get(key)
            if previous == new:
                continue
            if previous and (new is None or (previous["username"], previous["domain"], previous["login_time"]) !=
                            (new["username"], new["domain"], new["login_time"])):
                events.append(dict(previous, observed_at_utc=now, event="Nicht mehr gemeldet"))
            if new:
                events.append(dict(new, observed_at_utc=now, event="Sitzung erkannt" if previous is None else "Sitzung geändert"))
        if not events:
            return
        history = (self.events + events)[-200:]
        write_json_atomic(self.path, {"current": current, "events": history})
        self.current, self.events = current, history
