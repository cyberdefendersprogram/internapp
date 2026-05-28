"""Tests for sheets service using mocked gspread."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_worksheet():
    """Create a mock gspread worksheet."""
    ws = MagicMock()
    return ws


@pytest.fixture
def sheets_client():
    """Create a SheetsClient with mocked internals."""
    from app.services.sheets import SheetsClient

    client = SheetsClient()
    return client


class TestGetConfig:
    """Tests for get_config method."""

    def test_get_config_found(self, sheets_client, mock_worksheet):
        """Returns value when key exists."""
        mock_worksheet.get_all_records.return_value = [
            {"key": "program_title", "value": "Cyber Defenders Summer 2026"},
            {"key": "program_weeks", "value": "6"},
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.get_config("program_title")
            assert result == "Cyber Defenders Summer 2026"

    def test_get_config_not_found(self, sheets_client, mock_worksheet):
        """Returns None when key does not exist."""
        mock_worksheet.get_all_records.return_value = [
            {"key": "other_key", "value": "other_value"},
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.get_config("nonexistent")
            assert result is None

    def test_get_all_config(self, sheets_client, mock_worksheet):
        """Returns all config as dict."""
        mock_worksheet.get_all_records.return_value = [
            {"key": "program_title", "value": "CDP 2026"},
            {"key": "program_weeks", "value": "6"},
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.get_all_config()
            assert result["program_title"] == "CDP 2026"
            assert result["program_weeks"] == "6"


class TestGetAllTracks:
    """Tests for get_all_tracks method."""

    def test_get_all_tracks(self, sheets_client, mock_worksheet):
        """Returns list of TrackEntry objects."""
        mock_worksheet.get_all_records.return_value = [
            {
                "track_id": "track-1",
                "name": "Threat Intelligence",
                "description": "TI track",
                "employer_sponsor": "Jane Doe",
                "sponsor_email": "jane@company.com",
                "status": "active",
            },
            {
                "track_id": "track-2",
                "name": "Cloud Security",
                "description": "Cloud track",
                "employer_sponsor": "John Doe",
                "sponsor_email": "john@company.com",
                "status": "active",
            },
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            tracks = sheets_client.get_all_tracks()
            assert len(tracks) == 2
            assert tracks[0].track_id == "track-1"
            assert tracks[1].name == "Cloud Security"

    def test_get_track_by_id(self, mock_worksheet):
        """Returns matching track by track_id."""
        from app.services.cache import invalidate_all
        from app.services.sheets import SheetsClient

        invalidate_all()
        client = SheetsClient()
        mock_worksheet.get_all_records.return_value = [
            {
                "track_id": "track-99",
                "name": "Solo Track",
                "description": "",
                "employer_sponsor": "",
                "sponsor_email": "",
                "status": "active",
            },
        ]

        with patch.object(client, "_get_worksheet", return_value=mock_worksheet):
            track = client.get_track_by_id("track-99")
            assert track is not None
            assert track.name == "Solo Track"

    def test_get_track_by_sponsor_email(self, mock_worksheet):
        """Returns track matching sponsor email."""
        from app.services.cache import invalidate_all
        from app.services.sheets import SheetsClient

        invalidate_all()
        client = SheetsClient()
        mock_worksheet.get_all_records.return_value = [
            {
                "track_id": "t1",
                "name": "SpTrack",
                "description": "",
                "employer_sponsor": "X",
                "sponsor_email": "sponsor@co.com",
                "status": "active",
            },
        ]

        with patch.object(client, "_get_worksheet", return_value=mock_worksheet):
            track = client.get_track_by_sponsor_email("SPONSOR@CO.COM")
            assert track is not None
            assert track.track_id == "t1"


class TestGetRosterByEmail:
    """Tests for get_roster_by_email method."""

    def test_found(self, sheets_client, mock_worksheet):
        """Returns InternEntry when email matches."""
        mock_worksheet.get_all_records.return_value = [
            {
                "intern_id": "CDP-2026-001",
                "full_name": "Doe, Jane",
                "track_id": "track-1",
                "preferred_email": "jane@example.com",
                "claimed_at": "2026-06-01T10:00:00",
                "onboarding_completed_at": "",
                "preferred_name": "",
                "school": "",
                "year": "",
                "linkedin": "",
                "github": "",
                "bio": "",
                "last_login_at": "",
            }
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            intern = sheets_client.get_roster_by_email("jane@example.com")
            assert intern is not None
            assert intern.intern_id == "CDP-2026-001"

    def test_not_found(self, sheets_client, mock_worksheet):
        """Returns None when email not in roster."""
        mock_worksheet.get_all_records.return_value = []

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            intern = sheets_client.get_roster_by_email("nobody@example.com")
            assert intern is None

    def test_case_insensitive(self, sheets_client, mock_worksheet):
        """Email lookup is case-insensitive."""
        mock_worksheet.get_all_records.return_value = [
            {
                "intern_id": "CDP-001",
                "full_name": "Test",
                "track_id": "t1",
                "preferred_email": "Jane@Example.COM",
                "claimed_at": "",
                "onboarding_completed_at": "",
                "preferred_name": "",
                "school": "",
                "year": "",
                "linkedin": "",
                "github": "",
                "bio": "",
                "last_login_at": "",
            }
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            intern = sheets_client.get_roster_by_email("jane@example.com")
            assert intern is not None


class TestClaimIntern:
    """Tests for claim_intern method."""

    def test_claim_success(self, sheets_client, mock_worksheet):
        """Successfully claims unclaimed intern."""
        mock_worksheet.get_all_records.return_value = [
            {
                "intern_id": "CDP-001",
                "full_name": "Test",
                "track_id": "t1",
                "preferred_email": "",
                "claimed_at": "",
                "onboarding_completed_at": "",
                "preferred_name": "",
                "school": "",
                "year": "",
                "linkedin": "",
                "github": "",
                "bio": "",
                "last_login_at": "",
            }
        ]
        mock_worksheet.row_values.return_value = [
            "intern_id",
            "full_name",
            "track_id",
            "preferred_email",
            "preferred_name",
            "school",
            "year",
            "linkedin",
            "github",
            "bio",
            "claimed_at",
            "onboarding_completed_at",
            "last_login_at",
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.claim_intern("CDP-001", "test@example.com")
            assert result is True
            assert mock_worksheet.update_cell.called

    def test_claim_already_claimed(self, sheets_client, mock_worksheet):
        """Returns False when intern is already claimed."""
        mock_worksheet.get_all_records.return_value = [
            {
                "intern_id": "CDP-001",
                "full_name": "Test",
                "track_id": "t1",
                "preferred_email": "existing@example.com",
                "claimed_at": "2026-06-01T10:00:00",
                "onboarding_completed_at": "",
                "preferred_name": "",
                "school": "",
                "year": "",
                "linkedin": "",
                "github": "",
                "bio": "",
                "last_login_at": "",
            }
        ]

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.claim_intern("CDP-001", "new@example.com")
            assert result is False

    def test_claim_not_found(self, sheets_client, mock_worksheet):
        """Returns False when intern_id not in roster."""
        mock_worksheet.get_all_records.return_value = []

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.claim_intern("NONEXISTENT", "test@example.com")
            assert result is False


class TestAppendCheckin:
    """Tests for append_checkin method."""

    def test_append_checkin_success(self, sheets_client, mock_worksheet):
        """Successfully appends a check-in row."""
        mock_worksheet.row_values.return_value = [
            "submitted_at",
            "intern_id",
            "email",
            "week_number",
            "status_update",
            "blockers",
            "next_steps",
        ]

        data = {
            "submitted_at": "2026-06-15T10:00:00",
            "intern_id": "CDP-001",
            "email": "test@example.com",
            "week_number": 1,
            "status_update": "Built a thing",
            "blockers": "",
            "next_steps": "Keep building",
        }

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.append_checkin(data)
            assert result is True
            assert mock_worksheet.append_row.called


class TestAppendDeliverable:
    """Tests for append_deliverable method."""

    def test_append_deliverable_success(self, sheets_client, mock_worksheet):
        """Successfully appends a deliverable row."""
        mock_worksheet.row_values.return_value = [
            "submitted_at",
            "intern_id",
            "track_id",
            "week_number",
            "title",
            "url",
            "description",
        ]

        data = {
            "submitted_at": "2026-06-15T10:00:00",
            "intern_id": "CDP-001",
            "track_id": "track-1",
            "week_number": 1,
            "title": "Threat Report",
            "url": "https://github.com/example/report",
            "description": "My first deliverable",
        }

        with patch.object(sheets_client, "_get_worksheet", return_value=mock_worksheet):
            result = sheets_client.append_deliverable(data)
            assert result is True
            assert mock_worksheet.append_row.called
