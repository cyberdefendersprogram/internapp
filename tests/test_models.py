"""Tests for InternEntry and TrackEntry models."""

from datetime import datetime

from app.models.intern import InternEntry
from app.models.track import TrackEntry


class TestInternEntry:
    """Tests for InternEntry model."""

    def test_from_row_basic(self):
        """from_row creates InternEntry from dict."""
        row = {
            "intern_id": "CDP-2026-001",
            "full_name": "Doe, Jane",
            "track_id": "track-1",
            "preferred_email": "jane@example.com",
            "claimed_at": "2026-06-01T10:00:00",
            "onboarding_completed_at": "2026-06-01T11:00:00",
        }
        intern = InternEntry.from_row(row)
        assert intern.intern_id == "CDP-2026-001"
        assert intern.full_name == "Doe, Jane"
        assert intern.track_id == "track-1"
        assert intern.preferred_email == "jane@example.com"
        assert intern.claimed_at is not None
        assert intern.onboarding_completed_at is not None

    def test_is_claimed_true(self):
        """is_claimed is True when email and claimed_at are set."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Test User",
            preferred_email="test@example.com",
            claimed_at=datetime(2026, 6, 1),
        )
        assert intern.is_claimed is True

    def test_is_claimed_false_no_email(self):
        """is_claimed is False when email is missing."""
        intern = InternEntry(intern_id="CDP-001", full_name="Test User")
        assert intern.is_claimed is False

    def test_is_claimed_false_no_timestamp(self):
        """is_claimed is False when claimed_at is missing."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Test User",
            preferred_email="test@example.com",
        )
        assert intern.is_claimed is False

    def test_is_onboarded_true(self):
        """is_onboarded is True when onboarding_completed_at is set."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Test",
            onboarding_completed_at=datetime(2026, 6, 1),
        )
        assert intern.is_onboarded is True

    def test_is_onboarded_false(self):
        """is_onboarded is False when not completed."""
        intern = InternEntry(intern_id="CDP-001", full_name="Test")
        assert intern.is_onboarded is False

    def test_display_name_preferred(self):
        """display_name returns preferred_name when set."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Doe, Jane",
            preferred_name="Jane",
        )
        assert intern.display_name == "Jane"

    def test_display_name_from_full_name(self):
        """display_name extracts first name from 'Last, First' format."""
        intern = InternEntry(intern_id="CDP-001", full_name="Smith, Alice")
        assert intern.display_name == "Alice"

    def test_display_name_no_comma(self):
        """display_name returns full_name when no comma."""
        intern = InternEntry(intern_id="CDP-001", full_name="AliceSmith")
        assert intern.display_name == "AliceSmith"

    def test_email_property(self):
        """email property is alias for preferred_email."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Test",
            preferred_email="test@example.com",
        )
        assert intern.email == "test@example.com"

    def test_get_empty_profile_fields_all_empty(self):
        """Returns all profile fields when all are empty."""
        intern = InternEntry(intern_id="CDP-001", full_name="Test")
        empty = intern.get_empty_profile_fields()
        assert "preferred_name" in empty
        assert "school" in empty
        assert "year" in empty
        assert "linkedin" in empty
        assert "github" in empty
        assert "bio" in empty

    def test_get_empty_profile_fields_partial(self):
        """Returns only empty fields when some are filled."""
        intern = InternEntry(
            intern_id="CDP-001",
            full_name="Test",
            preferred_name="Jane",
            school="UC Berkeley",
        )
        empty = intern.get_empty_profile_fields()
        assert "preferred_name" not in empty
        assert "school" not in empty
        assert "year" in empty

    def test_from_row_empty_strings_become_none(self):
        """Empty strings in row dict become None."""
        row = {
            "intern_id": "CDP-001",
            "full_name": "Test",
            "preferred_email": "",
            "school": "",
        }
        intern = InternEntry.from_row(row)
        assert intern.preferred_email is None
        assert intern.school is None

    def test_from_row_sponsor_role_valid(self):
        """sponsor role is accepted and not overridden."""
        row = {"intern_id": "CDP-SP-01", "full_name": "Sponsor, Alice", "role": "sponsor"}
        intern = InternEntry.from_row(row)
        assert intern.role == "sponsor"

    def test_from_row_mentor_role_valid(self):
        """mentor role is accepted and not overridden."""
        row = {"intern_id": "CDP-M-01", "full_name": "Mentor, Bob", "role": "mentor"}
        intern = InternEntry.from_row(row)
        assert intern.role == "mentor"

    def test_from_row_unknown_role_defaults_to_intern(self):
        """Unknown role values fall back to intern."""
        row = {"intern_id": "CDP-001", "full_name": "Test", "role": "superuser"}
        intern = InternEntry.from_row(row)
        assert intern.role == "intern"


class TestTrackEntry:
    """Tests for TrackEntry model."""

    def test_from_row_basic(self):
        """from_row creates TrackEntry from dict."""
        row = {
            "track_id": "track-1",
            "name": "Threat Intelligence",
            "description": "A track about threat intel.",
            "employer_sponsor": "Jane Sponsor",
            "sponsor_email": "jane@company.com",
            "status": "active",
        }
        track = TrackEntry.from_row(row)
        assert track.track_id == "track-1"
        assert track.name == "Threat Intelligence"
        assert track.sponsor_email == "jane@company.com"
        assert track.is_active is True

    def test_is_active_true(self):
        """is_active is True for status='active'."""
        track = TrackEntry(track_id="t1", name="Test", status="active")
        assert track.is_active is True

    def test_is_active_false(self):
        """is_active is False for archived status."""
        track = TrackEntry(track_id="t1", name="Test", status="archived")
        assert track.is_active is False

    def test_is_active_case_insensitive(self):
        """is_active is case-insensitive."""
        track = TrackEntry(track_id="t1", name="Test", status="Active")
        assert track.is_active is True

    def test_from_row_defaults(self):
        """from_row provides sensible defaults."""
        row = {"track_id": "t1", "name": "Test"}
        track = TrackEntry.from_row(row)
        assert track.status == "active"
        assert track.description == ""
        assert track.employer_sponsor == ""
        assert track.sponsor_email == ""
