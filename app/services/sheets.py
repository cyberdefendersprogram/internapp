"""Google Sheets client for intern data access."""

import logging
import threading
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from app.config import settings
from app.models.applicant import ApplicantEntry
from app.models.intern import InternEntry
from app.models.track import TrackEntry
from app.services.cache import cached, invalidate

logger = logging.getLogger(__name__)


class SheetsUnavailableError(Exception):
    """Raised when the Google Sheets API is unreachable or rate-limited."""


# Google Sheets API scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Cache TTLs (in seconds)
CACHE_TTL_CONFIG = 600  # 10 minutes
CACHE_TTL_TRACKS = 900  # 15 minutes
CACHE_TTL_ROSTER = 600  # 10 minutes
CACHE_TTL_CHECKINS = 300  # 5 minutes
CACHE_TTL_DELIVERABLES = 300  # 5 minutes
CACHE_TTL_FEEDBACK = 300  # 5 minutes
CACHE_TTL_SURVEYS = 300  # 5 minutes
CACHE_TTL_PEER_REVIEWS = 300  # 5 minutes

# survey_type -> worksheet tab name. Add an entry here to support a new survey
# instance (e.g. "end_program") without touching any of the methods below.
SURVEY_SHEET_NAMES = {
    "mid_program": "Mid_Program_Survey",
}

SURVEY_HEADERS = [
    "submitted_at",
    "intern_id",
    "full_name",
    "track_id",
    "satisfaction",
    "coursework_connection",
    "growth_areas",
    "learned_most",
    "bootcamp_interest",
    "pace",
    "could_be_better",
    "additional_comments",
]

PEER_REVIEW_HEADERS = [
    "submitted_at",
    "reviewer_id",
    "reviewer_name",
    "reviewee_id",
    "reviewee_name",
    "rating",
    "strengths",
    "growth_areas",
    "comments",
]


class SheetsClient:
    """Client for interacting with Google Sheets."""

    def __init__(self):
        self._client: gspread.Client | None = None
        self._spreadsheet: gspread.Spreadsheet | None = None
        self._worksheets: dict[str, gspread.Worksheet] = {}
        self._email_log_headers: list[str] | None = None

    def _get_client(self) -> gspread.Client:
        """Get or create gspread client."""
        if self._client is None:
            sa_path = Path(settings.google_service_account_path)
            if not sa_path.exists():
                raise FileNotFoundError(f"Service account file not found: {sa_path}")

            creds = Credentials.from_service_account_file(str(sa_path), scopes=SCOPES)
            self._client = gspread.authorize(creds)
            logger.info("Google Sheets client initialized")

        return self._client

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        """Get or open the spreadsheet."""
        if self._spreadsheet is None:
            client = self._get_client()
            self._spreadsheet = client.open_by_key(settings.google_sheets_id)
            logger.info("Opened spreadsheet: %s", self._spreadsheet.title)

        return self._spreadsheet

    def _get_worksheet(self, name: str) -> gspread.Worksheet:
        """Get worksheet by name, caching the handle to avoid repeated metadata fetches."""
        if name not in self._worksheets:
            spreadsheet = self._get_spreadsheet()
            self._worksheets[name] = spreadsheet.worksheet(name)
        return self._worksheets[name]

    def check_connection(self) -> bool:
        """Check if Sheets connection is working.

        Validates config and credentials only — does NOT make a live API call,
        since health is checked every 30 s and a live call would exhaust quota.
        """
        try:
            if not settings.google_sheets_id or not settings.google_service_account_path:
                return False
            sa_path = Path(settings.google_service_account_path)
            if not sa_path.exists():
                return False
            self._get_client()
            return True
        except Exception as e:
            logger.warning("Sheets connection check failed: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Config methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_CONFIG, prefix="config")
    def get_config(self, key: str) -> str | None:
        """Get a config value by key."""
        try:
            worksheet = self._get_worksheet("Config")
            records = worksheet.get_all_records()

            for record in records:
                if record.get("key") == key:
                    return str(record.get("value", ""))

            return None
        except Exception as e:
            logger.error("Failed to get config '%s': %s", key, e)
            return None

    @cached(ttl_seconds=CACHE_TTL_CONFIG, prefix="config")
    def get_all_config(self) -> dict[str, str]:
        """Get all config values as a dictionary."""
        try:
            worksheet = self._get_worksheet("Config")
            records = worksheet.get_all_records()

            return {str(r.get("key", "")): str(r.get("value", "")) for r in records if r.get("key")}
        except Exception as e:
            logger.error("Failed to get all config: %s", e)
            return {}

    # -------------------------------------------------------------------------
    # Tracks methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_TRACKS, prefix="tracks")
    def get_all_tracks(self) -> list[TrackEntry]:
        """Get all tracks."""
        try:
            worksheet = self._get_worksheet("Tracks")
            records = worksheet.get_all_records()
            return [TrackEntry.from_row(r) for r in records if r.get("track_id")]
        except Exception as e:
            logger.error("Failed to get tracks: %s", e)
            return []

    def get_track_by_id(self, track_id: str) -> TrackEntry | None:
        """Get a track by track_id."""
        for track in self.get_all_tracks():
            if track.track_id == track_id:
                return track
        return None

    def get_track_by_sponsor_email(self, email: str) -> TrackEntry | None:
        """Get the first track where sponsor_email matches (legacy single-track)."""
        for track in self.get_all_tracks():
            if track.sponsor_email and track.sponsor_email.lower() == email.lower():
                return track
        return None

    def get_tracks_by_sponsor_email(self, email: str) -> list[TrackEntry]:
        """Get all tracks where sponsor_email matches (multi-track sponsors)."""
        return [
            t
            for t in self.get_all_tracks()
            if t.sponsor_email and t.sponsor_email.lower() == email.lower()
        ]

    def get_tracks_for_intern_entry(self, entry: "InternEntry") -> list[TrackEntry]:
        """Return all TrackEntry objects for a roster entry (handles multi-track)."""
        all_tracks = {t.track_id: t for t in self.get_all_tracks()}
        return [all_tracks[tid] for tid in entry.track_ids if tid in all_tracks]

    # -------------------------------------------------------------------------
    # Roster methods
    # -------------------------------------------------------------------------

    def get_roster_by_email(self, email: str) -> InternEntry | None:
        """Get roster entry by email address, filtered from cached get_all_roster."""
        email_lower = email.lower()
        for entry in self.get_all_roster():
            if (entry.preferred_email or "").lower() == email_lower:
                return entry
        return None

    def get_roster_by_name(self, name: str) -> InternEntry | None:
        """Get roster entry by preferred_name or display_name (case-insensitive).

        Used to resolve the free-text names in Roster.student_reviewer to actual
        intern records, since that column is populated by hand as names, not IDs.
        """
        name_lower = name.strip().lower()
        if not name_lower:
            return None
        for entry in self.get_all_roster():
            if (entry.preferred_name or "").strip().lower() == name_lower:
                return entry
        for entry in self.get_all_roster():
            if entry.display_name.strip().lower() == name_lower:
                return entry
        return None

    def resolve_reviewees(self, intern: InternEntry) -> list[InternEntry]:
        """Resolve an intern's reviewee_names (free-text names) to roster entries.

        Names that don't match a roster entry are skipped (logged) rather than erroring,
        since student_reviewer is a hand-entered column and typos are possible.
        """
        resolved = []
        for name in intern.reviewee_names:
            entry = self.get_roster_by_name(name)
            if entry:
                resolved.append(entry)
            else:
                logger.warning(
                    "Reviewer %s: no roster match for reviewee name '%s'", intern.intern_id, name
                )
        return resolved

    def get_roster_by_id(self, intern_id: str) -> InternEntry | None:
        """Get roster entry by intern_id, filtered from cached get_all_roster."""
        intern_id_str = str(intern_id)
        for entry in self.get_all_roster():
            if str(entry.intern_id) == intern_id_str:
                return entry
        return None

    @cached(ttl_seconds=CACHE_TTL_ROSTER, prefix="all_roster")
    def get_all_roster(self) -> list[InternEntry]:
        """Get all roster entries."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            return [InternEntry.from_row(r) for r in records if r.get("intern_id")]
        except Exception as e:
            logger.error("Failed to get all roster: %s", e)
            return []

    def claim_intern(self, intern_id: str, email: str) -> bool:
        """
        Claim an intern account by binding email to intern_id.

        Returns True if successful, False otherwise.
        """
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()

            for idx, record in enumerate(records):
                if str(record.get("intern_id")) == str(intern_id):
                    # Check not already claimed
                    if record.get("preferred_email") and record.get("claimed_at"):
                        logger.warning("Intern %s already claimed", intern_id)
                        return False

                    row_num = idx + 2
                    headers = worksheet.row_values(1)
                    email_col = headers.index("preferred_email") + 1
                    claimed_at_col = headers.index("claimed_at") + 1

                    now = datetime.utcnow().isoformat()
                    worksheet.update_cell(row_num, email_col, email)
                    worksheet.update_cell(row_num, claimed_at_col, now)

                    invalidate("roster")
                    invalidate("all_roster")

                    logger.info("Intern %s claimed by %s", intern_id, email)
                    return True

            logger.warning("Intern not found: %s", intern_id)
            return False

        except Exception as e:
            logger.error("Failed to claim intern %s: %s", intern_id, e)
            return False

    def update_roster(self, intern_id: str, **fields) -> bool:
        """
        Update roster entry fields.

        Returns True if successful.
        """
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            headers = worksheet.row_values(1)

            for idx, record in enumerate(records):
                if str(record.get("intern_id")) == str(intern_id):
                    row_num = idx + 2

                    for field_name, value in fields.items():
                        if field_name in headers:
                            col_num = headers.index(field_name) + 1
                            cell_value = value if value else ""
                            # RAW prevents Google Sheets from auto-converting ISO
                            # timestamps into date serials, which breaks _parse_datetime.
                            worksheet.update(
                                [[cell_value]],
                                gspread.utils.rowcol_to_a1(row_num, col_num),
                                value_input_option="RAW",
                            )

                    invalidate("roster")
                    invalidate("all_roster")

                    logger.info("Updated roster %s: %s", intern_id, list(fields.keys()))
                    return True

            logger.warning("Intern not found for update: %s", intern_id)
            return False

        except Exception as e:
            logger.error("Failed to update roster %s: %s", intern_id, e)
            return False

    # -------------------------------------------------------------------------
    # Check-in methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_CHECKINS, prefix="checkins")
    def get_checkins_for_intern(self, intern_id: str) -> list[dict]:
        """Get all check-ins for an intern."""
        try:
            worksheet = self._get_worksheet("Check_ins")
            records = worksheet.get_all_records()
            return [r for r in records if str(r.get("intern_id")) == str(intern_id)]
        except Exception as e:
            logger.error("Failed to get check-ins for %s: %s", intern_id, e)
            return []

    def append_checkin(self, data: dict) -> bool:
        """Append a check-in row."""
        try:
            worksheet = self._get_worksheet("Check_ins")
            headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            invalidate("checkins")
            logger.info(
                "Appended check-in: %s week %s", data.get("intern_id"), data.get("week_number")
            )
            return True
        except Exception as e:
            logger.error("Failed to append check-in: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Deliverable methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_DELIVERABLES, prefix="deliverables")
    def get_deliverables_for_intern(self, intern_id: str) -> list[dict]:
        """Get all deliverables for an intern."""
        try:
            worksheet = self._get_worksheet("Deliverables")
            records = worksheet.get_all_records()
            return [r for r in records if str(r.get("intern_id")) == str(intern_id)]
        except Exception as e:
            logger.error("Failed to get deliverables for %s: %s", intern_id, e)
            return []

    @cached(ttl_seconds=CACHE_TTL_DELIVERABLES, prefix="all_deliverables")
    def get_all_deliverables(self) -> list[dict]:
        """Get all deliverables."""
        try:
            worksheet = self._get_worksheet("Deliverables")
            return worksheet.get_all_records()
        except Exception as e:
            logger.error("Failed to get all deliverables: %s", e)
            return []

    def append_deliverable(self, data: dict) -> bool:
        """Append a deliverable row."""
        try:
            worksheet = self._get_worksheet("Deliverables")
            headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            invalidate("deliverables")
            invalidate("all_deliverables")
            logger.info("Appended deliverable: %s", data.get("intern_id"))
            return True
        except Exception as e:
            logger.error("Failed to append deliverable: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Feedback methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_FEEDBACK, prefix="feedback")
    def get_feedback_for_intern(self, intern_id: str) -> list[dict]:
        """Get all mentor feedback for an intern."""
        try:
            worksheet = self._get_worksheet("Mentor_Feedback")
            records = worksheet.get_all_records()
            return [r for r in records if str(r.get("intern_id")) == str(intern_id)]
        except Exception as e:
            logger.error("Failed to get feedback for %s: %s", intern_id, e)
            return []

    def append_feedback(self, data: dict) -> bool:
        """Append a mentor feedback row."""
        try:
            worksheet = self._get_worksheet("Mentor_Feedback")
            headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            invalidate("feedback")
            logger.info("Appended feedback: %s", data.get("intern_id"))
            return True
        except Exception as e:
            logger.error("Failed to append feedback: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Survey methods
    # -------------------------------------------------------------------------

    def _get_survey_worksheet(self, survey_type: str) -> gspread.Worksheet:
        """Get (or create) the worksheet tab for a given survey_type."""
        sheet_name = SURVEY_SHEET_NAMES.get(survey_type)
        if not sheet_name:
            raise ValueError(f"Unknown survey_type: {survey_type}")
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(SURVEY_HEADERS))
            ws.update([SURVEY_HEADERS], range_name="A1")
            logger.info("Created %s tab", sheet_name)
            return ws

    @cached(ttl_seconds=CACHE_TTL_SURVEYS, prefix="survey_responses")
    def _get_all_survey_responses(self, survey_type: str) -> list[dict]:
        """Fetch all responses for a survey_type (cached to avoid N+1 Sheets calls)."""
        try:
            ws = self._get_survey_worksheet(survey_type)
            return ws.get_all_records()
        except Exception as e:
            logger.error("Failed to get survey responses (%s): %s", survey_type, e)
            return []

    def get_survey_response(self, intern_id: str, survey_type: str) -> dict | None:
        """Return this intern's response to the given survey, or None if not submitted."""
        for r in self._get_all_survey_responses(survey_type):
            if str(r.get("intern_id")) == str(intern_id):
                return r
        return None

    def append_survey_response(self, survey_type: str, data: dict) -> bool:
        """Append a survey response row. Caller is responsible for checking for
        an existing response first (one submission per intern per survey_type)."""
        try:
            ws = self._get_survey_worksheet(survey_type)
            row = [data.get(h, "") for h in SURVEY_HEADERS]
            ws.append_row(row, value_input_option="RAW")
            invalidate("survey_responses")
            logger.info("Appended %s survey response: %s", survey_type, data.get("intern_id"))
            return True
        except Exception as e:
            logger.error("Failed to append %s survey response: %s", survey_type, e)
            return False

    # -------------------------------------------------------------------------
    # Peer review methods
    # -------------------------------------------------------------------------

    def _get_peer_reviews_worksheet(self) -> gspread.Worksheet:
        """Get (or create) the Peer_Reviews worksheet tab."""
        spreadsheet = self._get_spreadsheet()
        try:
            return spreadsheet.worksheet("Peer_Reviews")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title="Peer_Reviews", rows=1000, cols=len(PEER_REVIEW_HEADERS)
            )
            ws.update([PEER_REVIEW_HEADERS], range_name="A1")
            logger.info("Created Peer_Reviews tab")
            return ws

    @cached(ttl_seconds=CACHE_TTL_PEER_REVIEWS, prefix="peer_reviews")
    def get_all_peer_reviews(self) -> list[dict]:
        """Fetch entire Peer_Reviews tab once; cached to prevent N+1 Sheets calls."""
        try:
            ws = self._get_peer_reviews_worksheet()
            return ws.get_all_records()
        except Exception as e:
            logger.error("Failed to get peer reviews: %s", e)
            return []

    def get_reviews_by_reviewer(self, reviewer_id: str) -> list[dict]:
        """Return all reviews this intern has submitted about peers."""
        return [
            r for r in self.get_all_peer_reviews() if str(r.get("reviewer_id")) == str(reviewer_id)
        ]

    def get_reviews_for_reviewee(self, reviewee_id: str) -> list[dict]:
        """Return all reviews this intern has received from peers."""
        return [
            r for r in self.get_all_peer_reviews() if str(r.get("reviewee_id")) == str(reviewee_id)
        ]

    def get_peer_review(self, reviewer_id: str, reviewee_id: str) -> dict | None:
        """Return the existing review for this reviewer/reviewee pair, or None."""
        for r in self.get_reviews_by_reviewer(reviewer_id):
            if str(r.get("reviewee_id")) == str(reviewee_id):
                return r
        return None

    def upsert_peer_review(
        self,
        *,
        reviewer_id: str,
        reviewer_name: str,
        reviewee_id: str,
        reviewee_name: str,
        rating: str,
        strengths: str,
        growth_areas: str,
        comments: str,
    ) -> bool:
        """Append a new peer review row (or update the existing one for this pair)."""
        try:
            ws = self._get_peer_reviews_worksheet()
            records = ws.get_all_records()
            now = datetime.utcnow().isoformat()
            data = {
                "submitted_at": now,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "reviewee_id": reviewee_id,
                "reviewee_name": reviewee_name,
                "rating": rating,
                "strengths": strengths,
                "growth_areas": growth_areas,
                "comments": comments,
            }

            for idx, record in enumerate(records):
                if str(record.get("reviewer_id")) == str(reviewer_id) and str(
                    record.get("reviewee_id")
                ) == str(reviewee_id):
                    row_num = idx + 2  # 1-based + header
                    row = [data.get(h, "") for h in PEER_REVIEW_HEADERS]
                    ws.update(
                        [row],
                        gspread.utils.rowcol_to_a1(row_num, 1)
                        + ":"
                        + gspread.utils.rowcol_to_a1(row_num, len(PEER_REVIEW_HEADERS)),
                        value_input_option="RAW",
                    )
                    invalidate("peer_reviews")
                    logger.info("Updated peer review %s -> %s", reviewer_id, reviewee_id)
                    return True

            row = [data.get(h, "") for h in PEER_REVIEW_HEADERS]
            ws.append_row(row, value_input_option="RAW")
            invalidate("peer_reviews")
            logger.info("Appended peer review %s -> %s", reviewer_id, reviewee_id)
            return True
        except Exception as e:
            logger.error("Failed to upsert peer review %s -> %s: %s", reviewer_id, reviewee_id, e)
            return False

    # -------------------------------------------------------------------------
    # Email log methods
    # -------------------------------------------------------------------------

    def append_email_log(self, data: dict) -> bool:
        """Append an email log row."""
        try:
            worksheet = self._get_worksheet("Email_Log")
            if self._email_log_headers is None:
                self._email_log_headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in self._email_log_headers]
            worksheet.append_row(row, value_input_option="RAW")
            return True
        except Exception as e:
            logger.error("Failed to append email log: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Magic Link audit methods
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Applicant methods (separate spreadsheet)
    # -------------------------------------------------------------------------

    def _get_applicant_spreadsheet(self) -> gspread.Spreadsheet:
        """Open the applicant spreadsheet (different from the intern one)."""
        if not settings.applicant_sheets_id:
            raise ValueError("APPLICANT_SHEETS_ID is not configured")
        client = self._get_client()
        return client.open_by_key(settings.applicant_sheets_id)

    def _get_applicant_feedback_sheet(self) -> gspread.Worksheet:
        """Get (or create) the Applicant_Feedback worksheet in the applicant spreadsheet."""
        spreadsheet = self._get_applicant_spreadsheet()
        try:
            return spreadsheet.worksheet("Applicant_Feedback")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="Applicant_Feedback", rows=1000, cols=10)
            ws.update(
                [["applicant_row", "reviewer_email", "reviewer_name", "submitted_at", "feedback"]],
                range_name="A1",
            )
            logger.info("Created Applicant_Feedback tab")
            return ws

    @cached(ttl_seconds=120, prefix="applicants")
    def get_all_applicants(self) -> list[ApplicantEntry]:
        """Return all applicant rows (skips header row 1).
        Raises SheetsUnavailableError on quota/API errors."""
        try:
            sheet = self._get_applicant_spreadsheet().sheet1
            all_rows = sheet.get_all_values()
            if len(all_rows) < 2:
                return []
            return [
                ApplicantEntry.from_row(row_index=i + 2, row=row)
                for i, row in enumerate(all_rows[1:])
                if any(cell.strip() for cell in row)
            ]
        except gspread.exceptions.APIError as e:
            logger.error("Sheets API error getting applicants: %s", e)
            raise SheetsUnavailableError(str(e)) from e
        except Exception as e:
            logger.error("Failed to get applicants: %s", e)
            return []

    @cached(ttl_seconds=120, prefix="applicant_row")
    def get_applicant_by_row(self, row_index: int) -> ApplicantEntry | None:
        """Return the applicant at the given 1-based row index.
        Raises SheetsUnavailableError on API/quota errors so callers can return 503."""
        try:
            sheet = self._get_applicant_spreadsheet().sheet1
            row = sheet.row_values(row_index)
            if not any(cell.strip() for cell in row):
                return None  # genuinely empty row → 404
            return ApplicantEntry.from_row(row_index=row_index, row=row)
        except gspread.exceptions.APIError as e:
            logger.error("Sheets API error getting applicant row %s: %s", row_index, e)
            raise SheetsUnavailableError(str(e)) from e
        except Exception as e:
            logger.error("Failed to get applicant row %s: %s", row_index, e)
            return None

    def save_decision(self, row_index: int, decision: str) -> bool:
        """Write the admin decision to column I (9) of the applicant sheet."""
        try:
            sheet = self._get_applicant_spreadsheet().sheet1
            sheet.update_cell(row_index, 9, decision)
            invalidate("applicant_row")
            invalidate("applicants")
            logger.info("Decision '%s' saved for applicant row %s", decision, row_index)
            return True
        except Exception as e:
            logger.error("Failed to save decision for row %s: %s", row_index, e)
            return False

    # Role prefix map: role → letter used in ID (e.g. "intern" → "I")
    _ROLE_PREFIX = {"intern": "I", "mentor": "M", "sponsor": "S", "admin": "A"}

    def _next_intern_id(self, role: str = "intern") -> str:
        """Generate the next sequential CDP-YYYY-X## id for the given role."""
        import re

        prefix = self._ROLE_PREFIX.get(role, "I")
        pattern = re.compile(rf"^CDP-\d{{4}}-{prefix}(\d+)$")
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            max_n = 0
            for r in records:
                m = pattern.match(str(r.get("intern_id", "")))
                if m:
                    max_n = max(max_n, int(m.group(1)))
            year = datetime.utcnow().year
            return f"CDP-{year}-{prefix}{max_n + 1:02d}"
        except Exception as e:
            logger.error("Failed to generate intern_id (role=%s): %s", role, e)
            import random

            return f"CDP-{datetime.utcnow().year}-{prefix}{random.randint(90, 99)}"

    def admit_applicant(
        self,
        row_index: int,
        full_name: str,
        track_id: str,
        intern_id: str,
        preferred_email: str = "",
    ) -> bool:
        """
        Write a new row to the Roster and stamp Admitted_At (col J) on the applicant sheet.
        Returns True on success.
        """
        try:
            roster_ws = self._get_worksheet("Roster")
            headers = roster_ws.row_values(1)

            # Build roster row aligned to current headers
            data = {
                "intern_id": intern_id,
                "full_name": full_name,
                "track_id": track_id,
                "role": "intern",
                "preferred_email": preferred_email,
            }
            row = [data.get(h, "") for h in headers]
            roster_ws.append_row(row, value_input_option="RAW")
            invalidate("roster")
            invalidate("all_roster")

            # Stamp admitted_at on applicant sheet (col J = 10)
            app_sheet = self._get_applicant_spreadsheet().sheet1
            app_sheet.update_cell(row_index, 10, datetime.utcnow().isoformat())
            invalidate("applicant_row")
            invalidate("applicants")

            logger.info("Admitted applicant row %s as %s (%s)", row_index, intern_id, full_name)
            return True
        except Exception as e:
            logger.error("Failed to admit applicant row %s: %s", row_index, e)
            return False

    @cached(ttl_seconds=120, prefix="all_applicant_feedback")
    def _get_all_applicant_feedback_raw(self) -> list[dict]:
        """Fetch entire Applicant_Feedback tab once; cached to prevent N+1 Sheets calls."""
        try:
            ws = self._get_applicant_feedback_sheet()
            return ws.get_all_records()
        except Exception as e:
            logger.error("Failed to bulk-fetch applicant feedback: %s", e)
            return []

    def get_applicant_feedback(self, applicant_row: int) -> list[dict]:
        """Return all feedback entries for one applicant."""
        records = self._get_all_applicant_feedback_raw()
        return [r for r in records if str(r.get("applicant_row")) == str(applicant_row)]

    def get_all_applicant_feedback_counts(self) -> dict[int, int]:
        """Return {applicant_row: feedback_count} for all applicants in one API call."""
        counts: dict[int, int] = {}
        for r in self._get_all_applicant_feedback_raw():
            try:
                row = int(r.get("applicant_row", 0))
            except (ValueError, TypeError):
                continue
            counts[row] = counts.get(row, 0) + 1
        return counts

    def get_reviewer_feedback(self, applicant_row: int, reviewer_email: str) -> str:
        """Return this reviewer's existing feedback for an applicant, or empty string."""
        for entry in self.get_applicant_feedback(applicant_row):
            if entry.get("reviewer_email", "").lower() == reviewer_email.lower():
                return str(entry.get("feedback", ""))
        return ""

    def upsert_applicant_feedback(
        self, applicant_row: int, reviewer_email: str, reviewer_name: str, feedback: str
    ) -> bool:
        """Append a new feedback row (or update existing row for this reviewer)."""
        try:
            ws = self._get_applicant_feedback_sheet()
            records = ws.get_all_records()
            now = datetime.utcnow().isoformat()

            for idx, record in enumerate(records):
                if (
                    str(record.get("applicant_row")) == str(applicant_row)
                    and record.get("reviewer_email", "").lower() == reviewer_email.lower()
                ):
                    row_num = idx + 2  # 1-based + header
                    ws.update(f"D{row_num}:E{row_num}", [[now, feedback]])
                    logger.info(
                        "Updated feedback for applicant row %s by %s", applicant_row, reviewer_email
                    )
                    return True

            ws.append_row(
                [applicant_row, reviewer_email, reviewer_name, now, feedback],
                value_input_option="RAW",
            )
            logger.info(
                "Appended feedback for applicant row %s by %s", applicant_row, reviewer_email
            )
            invalidate("all_applicant_feedback")
            return True
        except Exception as e:
            logger.error("Failed to upsert feedback for row %s: %s", applicant_row, e)
            return False

    # -------------------------------------------------------------------------
    # Discord identity linking methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=120, prefix="roster_discord")
    def get_roster_by_discord_id(self, discord_id: str) -> "InternEntry | None":
        """Get roster entry by Discord snowflake ID."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            for record in records:
                if str(record.get("discord_id", "")) == str(discord_id):
                    return InternEntry.from_row(record)
            return None
        except Exception as e:
            logger.error("Failed to get roster by discord_id %s: %s", discord_id, e)
            return None

    def link_discord_id(self, intern_id: str, discord_id: str) -> bool:
        """Write discord_id to Roster for an intern."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            headers = worksheet.row_values(1)

            if "discord_id" not in headers:
                logger.error("Roster sheet missing discord_id column")
                return False

            for idx, record in enumerate(records):
                if str(record.get("intern_id")) == str(intern_id):
                    row_num = idx + 2
                    col = headers.index("discord_id") + 1
                    worksheet.update_cell(row_num, col, discord_id)
                    invalidate("roster")
                    invalidate("all_roster")
                    invalidate("roster_discord")
                    logger.info("Linked discord_id %s to intern %s", discord_id, intern_id)
                    return True

            logger.warning("Intern not found for discord link: %s", intern_id)
            return False
        except Exception as e:
            logger.error("Failed to link discord_id for %s: %s", intern_id, e)
            return False

    def set_discord_notify(self, intern_id: str, notify: bool) -> bool:
        """Set discord_notify preference for an intern."""
        return self.update_roster(intern_id, discord_notify="true" if notify else "false")

    def append_magic_link_request(self, data: dict) -> bool:
        """Append a magic link request to audit log (Email_Log sheet)."""
        try:
            worksheet = self._get_worksheet("Email_Log")
            headers = worksheet.row_values(1)
            log_data = {
                "sent_at": data.get("requested_at", ""),
                "sender_email": "",
                "recipient_email": data.get("email", ""),
                "recipient_name": "",
                "subject": "Magic Link Request",
                "template": "magic_link",
                "status": data.get("result", ""),
                "note": data.get("note", ""),
                "ip_address": data.get("ip_address", ""),
            }
            row = [log_data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            return True
        except Exception as e:
            logger.error("Failed to append magic link request: %s", e)
            return False


# Thread-local storage so each thread gets its own gspread session
# (requests.Session used by gspread is not thread-safe)
_thread_local = threading.local()


def get_sheets_client() -> SheetsClient:
    """Get a per-thread SheetsClient instance."""
    if not hasattr(_thread_local, "client"):
        _thread_local.client = SheetsClient()
    return _thread_local.client
