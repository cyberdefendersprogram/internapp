"""Track data model."""

from dataclasses import dataclass


@dataclass
class TrackEntry:
    """Represents a project track from the Tracks sheet."""

    track_id: str
    name: str
    description: str = ""
    employer_sponsor: str = ""
    sponsor_email: str = ""
    status: str = "active"

    @property
    def is_active(self) -> bool:
        """Check if track is active."""
        return self.status.lower() == "active"

    @classmethod
    def from_row(cls, row: dict) -> "TrackEntry":
        """Create TrackEntry from a sheet row dictionary."""
        return cls(
            track_id=str(row.get("track_id", "")),
            name=row.get("name", ""),
            description=row.get("description", ""),
            employer_sponsor=row.get("employer_sponsor", ""),
            sponsor_email=row.get("sponsor_email", ""),
            status=row.get("status", "active"),
        )
