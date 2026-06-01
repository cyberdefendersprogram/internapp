"""Intern data model."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class InternEntry:
    """Represents an intern from the Roster sheet."""

    intern_id: str
    full_name: str
    track_id: str = ""
    role: str = "intern"  # intern | mentor | admin
    preferred_email: str | None = None
    preferred_name: str | None = None
    school: str | None = None
    year: str | None = None
    linkedin: str | None = None
    github: str | None = None
    bio: str | None = None
    claimed_at: datetime | None = None
    onboarding_completed_at: datetime | None = None
    last_login_at: datetime | None = None
    discord_id: str | None = None
    discord_notify: bool = True

    @property
    def is_claimed(self) -> bool:
        """Check if intern has claimed their account."""
        return self.preferred_email is not None and self.claimed_at is not None

    @property
    def is_onboarded(self) -> bool:
        """Check if intern has completed onboarding."""
        return self.onboarding_completed_at is not None

    @property
    def display_name(self) -> str:
        """Get the name to display (preferred name or parsed first name from full_name)."""
        if self.preferred_name:
            return self.preferred_name
        # full_name is "Last, First" format — extract first name
        if self.full_name and "," in self.full_name:
            parts = self.full_name.split(",", 1)
            if len(parts) > 1:
                return parts[1].strip().split()[0]
        return self.full_name or "Intern"

    @property
    def email(self) -> str | None:
        """Alias for preferred_email."""
        return self.preferred_email

    @classmethod
    def from_row(cls, row: dict) -> "InternEntry":
        """Create InternEntry from a sheet row dictionary."""
        raw_role = str(row.get("role", "")).strip().lower()
        role = raw_role if raw_role in ("intern", "mentor", "admin", "sponsor") else "intern"
        return cls(
            intern_id=str(row.get("intern_id", "")),
            full_name=row.get("full_name", ""),
            track_id=str(row.get("track_id", "")),
            role=role,
            preferred_email=row.get("preferred_email") or None,
            preferred_name=row.get("preferred_name") or None,
            school=row.get("school") or None,
            year=row.get("year") or None,
            linkedin=row.get("linkedin") or None,
            github=row.get("github") or None,
            bio=row.get("bio") or None,
            claimed_at=_parse_datetime(row.get("claimed_at")),
            onboarding_completed_at=_parse_datetime(row.get("onboarding_completed_at")),
            last_login_at=_parse_datetime(row.get("last_login_at")),
            discord_id=row.get("discord_id") or None,
            discord_notify=str(row.get("discord_notify", "true")).lower() not in ("false", "0", ""),
        )

    def get_empty_profile_fields(self) -> list[str]:
        """Get list of profile fields that are empty (for onboarding)."""
        profile_fields = [
            "preferred_name",
            "school",
            "year",
            "linkedin",
            "github",
            "bio",
        ]
        return [f for f in profile_fields if not getattr(self, f)]


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    try:
        if "." in str(value):
            return datetime.fromisoformat(str(value))
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
