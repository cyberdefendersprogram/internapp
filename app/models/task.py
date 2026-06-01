"""Task data model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TaskEntry:
    """Represents a task from the Tasks sheet."""

    task_id: str
    title: str
    task_type: str = "system"  # system | assigned | self
    assigned_to: str = ""  # intern_id | "track:track-1" | "all"
    assigned_by: str = "system"  # intern_id | "system"
    track_id: str = ""
    week_number: int | None = None
    due_week: int | None = None
    status: str = "todo"  # todo | done | skipped
    priority: str = "normal"  # normal | high
    linked_feature: str = ""  # checkin | deliverable | onboarding | blank
    source: str = "system"  # web | discord | system
    description: str = ""
    skip_reason: str = ""
    created_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "TaskEntry":
        """Create TaskEntry from a sheet row dictionary."""
        return cls(
            task_id=str(row.get("task_id", "")),
            title=str(row.get("title", "")),
            task_type=str(row.get("task_type", "system")),
            assigned_to=str(row.get("assigned_to", "")),
            assigned_by=str(row.get("assigned_by", "system")),
            track_id=str(row.get("track_id", "")),
            week_number=_parse_int(row.get("week_number")),
            due_week=_parse_int(row.get("due_week")),
            status=str(row.get("status", "todo")),
            priority=str(row.get("priority", "normal")),
            linked_feature=str(row.get("linked_feature", "")),
            source=str(row.get("source", "system")),
            description=str(row.get("description", "")),
            skip_reason=str(row.get("skip_reason", "")),
            created_at=_parse_datetime(row.get("created_at")),
            completed_at=_parse_datetime(row.get("completed_at")),
        )

    def to_row(self, headers: list[str]) -> list:
        """Convert to a sheet row in header order."""
        data = {
            "task_id": self.task_id,
            "title": self.title,
            "task_type": self.task_type,
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "track_id": self.track_id,
            "week_number": self.week_number or "",
            "due_week": self.due_week or "",
            "status": self.status,
            "priority": self.priority,
            "linked_feature": self.linked_feature,
            "source": self.source,
            "description": self.description,
            "skip_reason": self.skip_reason,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
        }
        return [data.get(h, "") for h in headers]


def _parse_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        if "." in str(value):
            return datetime.fromisoformat(str(value))
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
