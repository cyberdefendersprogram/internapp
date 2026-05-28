"""Google Sheets client for intern data access."""

import logging
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

# Cache TTLs (in seconds) per SPEC section 14
CACHE_TTL_CONFIG = 300  # 5 minutes
CACHE_TTL_TRACKS = 600  # 10 minutes
CACHE_TTL_ROSTER = 120  # 2 minutes
CACHE_TTL_CHECKINS = 120  # 2 minutes
CACHE_TTL_DELIVERABLES = 120  # 2 minutes
CACHE_TTL_ATTENDANCE = 120  # 2 minutes
CACHE_TTL_FEEDBACK = 120  # 2 minutes


class SheetsClient:
    """Client for interacting with Google Sheets."""

    def __init__(self):
        self._client: gspread.Client | None = None
        self._spreadsheet: gspread.Spreadsheet | None = None

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
        """Get worksheet by name."""
        spreadsheet = self._get_spreadsheet()
        return spreadsheet.worksheet(name)

    def check_connection(self) -> bool:
        """Check if Sheets connection is working."""
        try:
            if not settings.google_sheets_id or not settings.google_service_account_path:
                return False

            sa_path = Path(settings.google_service_account_path)
            if not sa_path.exists():
                return False

            spreadsheet = self._get_spreadsheet()
            spreadsheet.worksheet("Config")
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
        """Get the track where sponsor_email matches."""
        for track in self.get_all_tracks():
            if track.sponsor_email.lower() == email.lower():
                return track
        return None

    # -------------------------------------------------------------------------
    # Roster methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_ROSTER, prefix="roster")
    def get_roster_by_email(self, email: str) -> InternEntry | None:
        """Get roster entry by email address."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()

            for record in records:
                if record.get("preferred_email", "").lower() == email.lower():
                    return InternEntry.from_row(record)

            return None
        except gspread.exceptions.APIError as e:
            logger.error("Sheets API error getting roster by email '%s': %s", email, e)
            raise SheetsUnavailableError(str(e)) from e
        except Exception as e:
            logger.error("Failed to get roster by email '%s': %s", email, e)
            return None

    @cached(ttl_seconds=CACHE_TTL_ROSTER, prefix="roster")
    def get_roster_by_id(self, intern_id: str) -> InternEntry | None:
        """Get roster entry by intern_id."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()

            for record in records:
                if str(record.get("intern_id")) == str(intern_id):
                    return InternEntry.from_row(record)

            return None
        except gspread.exceptions.APIError as e:
            logger.error("Sheets API error getting roster by id '%s': %s", intern_id, e)
            raise SheetsUnavailableError(str(e)) from e
        except Exception as e:
            logger.error("Failed to get roster by id '%s': %s", intern_id, e)
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
                            worksheet.update_cell(row_num, col_num, value if value else "")

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
    # Attendance methods
    # -------------------------------------------------------------------------

    @cached(ttl_seconds=CACHE_TTL_ATTENDANCE, prefix="attendance")
    def get_attendance(self) -> list[dict]:
        """Get all attendance records."""
        try:
            worksheet = self._get_worksheet("Attendance")
            return worksheet.get_all_records()
        except Exception as e:
            logger.error("Failed to get attendance: %s", e)
            return []

    def append_attendance(self, data: dict) -> bool:
        """Append an attendance row."""
        try:
            worksheet = self._get_worksheet("Attendance")
            headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            invalidate("attendance")
            logger.info(
                "Appended attendance: %s on %s", data.get("intern_id"), data.get("session_date")
            )
            return True
        except Exception as e:
            logger.error("Failed to append attendance: %s", e)
            return False

    # -------------------------------------------------------------------------
    # Email log methods
    # -------------------------------------------------------------------------

    def append_email_log(self, data: dict) -> bool:
        """Append an email log row."""
        try:
            worksheet = self._get_worksheet("Email_Log")
            headers = worksheet.row_values(1)
            row = [data.get(h, "") for h in headers]
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

    def _next_intern_id(self) -> str:
        """Generate the next sequential CDP-YYYY-NNN intern_id from the Roster."""
        try:
            worksheet = self._get_worksheet("Roster")
            records = worksheet.get_all_records()
            max_n = 0
            for r in records:
                iid = str(r.get("intern_id", ""))
                parts = iid.split("-")
                if len(parts) == 3 and parts[2].isdigit():
                    max_n = max(max_n, int(parts[2]))
            year = datetime.utcnow().year
            return f"CDP-{year}-{max_n + 1:03d}"
        except Exception as e:
            logger.error("Failed to generate intern_id: %s", e)
            import random

            return f"CDP-{datetime.utcnow().year}-{random.randint(900, 999)}"

    def admit_applicant(
        self,
        row_index: int,
        full_name: str,
        track_id: str,
        intern_id: str,
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

    @cached(ttl_seconds=60, prefix="applicant_feedback")
    def get_applicant_feedback(self, applicant_row: int) -> list[dict]:
        """Return all feedback entries for one applicant, sorted oldest-first."""
        try:
            ws = self._get_applicant_feedback_sheet()
            records = ws.get_all_records()
            return [r for r in records if str(r.get("applicant_row")) == str(applicant_row)]
        except Exception as e:
            logger.error("Failed to get applicant feedback for row %s: %s", applicant_row, e)
            return []

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
            invalidate("applicant_feedback")
            return True
        except Exception as e:
            logger.error("Failed to upsert feedback for row %s: %s", applicant_row, e)
            return False

    def append_magic_link_request(self, data: dict) -> bool:
        """Append a magic link request to audit log (Email_Log sheet)."""
        try:
            worksheet = self._get_worksheet("Email_Log")
            headers = worksheet.row_values(1)
            # Map to Email_Log columns
            log_data = {
                "sent_at": data.get("requested_at", ""),
                "sender_email": "",
                "recipient_email": data.get("email", ""),
                "recipient_name": "",
                "subject": "Magic Link Request",
                "template": "magic_link",
                "status": data.get("result", ""),
                "note": data.get("note", ""),
            }
            row = [log_data.get(h, "") for h in headers]
            worksheet.append_row(row, value_input_option="RAW")
            return True
        except Exception as e:
            logger.error("Failed to append magic link request: %s", e)
            return False


# Singleton instance
_sheets_client: SheetsClient | None = None


def get_sheets_client() -> SheetsClient:
    """Get the singleton SheetsClient instance."""
    global _sheets_client
    if _sheets_client is None:
        _sheets_client = SheetsClient()
    return _sheets_client
