"""Applicant data model (pre-intern, interview stage)."""

from dataclasses import dataclass

DECISIONS = ("Pending", "Accept", "Waitlist", "Decline")


@dataclass
class ApplicantEntry:
    row_index: int  # 1-based sheet row (used for cell updates)
    email: str  # col B — applicant's own email (from Google Form)
    full_name: str  # col C
    technical_project: str
    hours_availability: str
    track_interest: str
    linkedin: str
    notes: str
    decision: str = "Pending"  # col I — set by admin during interview
    admitted_at: str = ""  # col J — stamped on roster promotion

    @classmethod
    def from_row(cls, row_index: int, row: list[str]) -> "ApplicantEntry":
        def get(i: int) -> str:
            return row[i].strip() if i < len(row) else ""

        # Google Form response column layout:
        # 0: Timestamp  1: Email  2: Full Name  3: Technical Project
        # 4: Hours/Availability  5: Track Interest  6: LinkedIn  7: Notes
        # 8: Decision (written by app)  9: Admitted_At (written by app)
        raw_decision = get(8)
        decision = raw_decision if raw_decision in DECISIONS else "Pending"
        return cls(
            row_index=row_index,
            email=get(1),
            full_name=get(2),
            technical_project=get(3),
            hours_availability=get(4),
            track_interest=get(5),
            linkedin=get(6),
            notes=get(7),
            decision=decision,
            admitted_at=get(9),
        )

    @property
    def display_name(self) -> str:
        return self.full_name or "(No name)"

    @property
    def is_admitted(self) -> bool:
        return bool(self.admitted_at)
