"""Local reservation model for the test calendar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass
class Reservation:
    """A time range reserved for one workstation."""

    workstation_id: str
    title: str
    start: datetime
    end: datetime
    reserved_by: str
    color: str = "#5d86a4"
    reservation_id: str = field(default_factory=lambda: uuid4().hex)

    def overlaps_day(self, day_start: datetime, day_end: datetime) -> bool:
        return self.start < day_end and self.end > day_start

    def to_dict(self) -> dict[str, str]:
        return {
            "reservation_id": self.reservation_id,
            "workstation_id": self.workstation_id,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reserved_by": self.reserved_by,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Reservation:
        return cls(
            reservation_id=data.get("reservation_id", uuid4().hex),
            workstation_id=data["workstation_id"],
            title=data.get("title", "Reserviert"),
            start=datetime.fromisoformat(data["start"]),
            end=datetime.fromisoformat(data["end"]),
            reserved_by=data.get("reserved_by", ""),
            color=data.get("color", "#5d86a4"),
        )


__all__ = ["Reservation"]
