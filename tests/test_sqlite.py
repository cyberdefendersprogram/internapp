"""Tests for SQLite persistence layer — meeting notes and intern cache."""

import uuid

import pytest

from app.db.sqlite import (
    add_meeting_note,
    delete_meeting_note,
    get_notes_for_intern,
    get_sponsor_notes_for_intern,
    init_db,
    update_meeting_note,
)


@pytest.fixture(autouse=True)
def fresh_db(setup_test_env):
    """Ensure DB is initialised before every test."""
    init_db()


def _uid() -> str:
    """Generate a unique intern ID that won't collide across test runs."""
    return f"TEST-{uuid.uuid4().hex[:8]}"


# ── helpers ───────────────────────────────────────────────────────────────────


def _add(intern_id, meeting_type="mentor_1on1", visibility="all", **kwargs):
    defaults = dict(
        week_number=1,
        meeting_date="2026-06-15",
        notes="Test note",
        action_items="",
        created_by="mentor@example.com",
        visibility=visibility,
    )
    defaults.update(kwargs)
    return add_meeting_note(intern_id=intern_id, meeting_type=meeting_type, **defaults)


# ── add_meeting_note ──────────────────────────────────────────────────────────


class TestAddMeetingNote:
    def test_returns_uuid(self):
        note_id = _add(_uid())
        assert isinstance(note_id, str) and len(note_id) == 36

    def test_note_appears_in_list(self):
        iid = _uid()
        _add(iid, notes="Hello world")
        notes = get_notes_for_intern(iid)
        assert any(n["notes"] == "Hello world" for n in notes)

    def test_separate_interns_isolated(self):
        a, b = _uid(), _uid()
        _add(a, notes="Intern A note")
        _add(b, notes="Intern B note")
        assert all(n["intern_id"] == a for n in get_notes_for_intern(a))
        assert all(n["intern_id"] == b for n in get_notes_for_intern(b))

    def test_action_items_stored(self):
        iid = _uid()
        _add(iid, action_items="- Follow up\n- Send report")
        notes = get_notes_for_intern(iid)
        assert notes[0]["action_items"] == "- Follow up\n- Send report"

    def test_all_meeting_types_accepted(self):
        iid = _uid()
        for mt in ("mentor_1on1", "sponsor_checkin", "other"):
            _add(iid, meeting_type=mt)
        types = {n["meeting_type"] for n in get_notes_for_intern(iid)}
        assert types == {"mentor_1on1", "sponsor_checkin", "other"}


# ── get_notes_for_intern ──────────────────────────────────────────────────────


class TestGetNotesForIntern:
    def test_returns_newest_first(self):
        iid = _uid()
        _add(iid, meeting_date="2026-06-10", notes="older")
        _add(iid, meeting_date="2026-06-15", notes="newer")
        assert get_notes_for_intern(iid)[0]["notes"] == "newer"

    def test_visibility_none_returns_all(self):
        iid = _uid()
        _add(iid, visibility="all", notes="shared")
        _add(iid, visibility="mentor_admin", notes="private")
        texts = {n["notes"] for n in get_notes_for_intern(iid, visibility=None)}
        assert "shared" in texts and "private" in texts

    def test_visibility_all_filters_private(self):
        iid = _uid()
        _add(iid, visibility="all", notes="shared")
        _add(iid, visibility="mentor_admin", notes="private")
        texts = {n["notes"] for n in get_notes_for_intern(iid, visibility="all")}
        assert "shared" in texts and "private" not in texts

    def test_empty_when_no_notes(self):
        assert get_notes_for_intern(_uid()) == []


# ── get_sponsor_notes_for_intern ──────────────────────────────────────────────


class TestGetSponsorNotesForIntern:
    def test_returns_only_sponsor_checkin_all(self):
        iid = _uid()
        _add(iid, meeting_type="sponsor_checkin", visibility="all", notes="sponsor public")
        _add(
            iid, meeting_type="sponsor_checkin", visibility="mentor_admin", notes="sponsor private"
        )
        _add(iid, meeting_type="mentor_1on1", visibility="all", notes="mentor note")
        notes = get_sponsor_notes_for_intern(iid)
        assert len(notes) == 1
        assert notes[0]["notes"] == "sponsor public"

    def test_empty_when_no_sponsor_notes(self):
        iid = _uid()
        _add(iid, meeting_type="mentor_1on1", visibility="all")
        assert get_sponsor_notes_for_intern(iid) == []


# ── delete_meeting_note ───────────────────────────────────────────────────────


class TestDeleteMeetingNote:
    def test_delete_removes_note(self):
        iid = _uid()
        note_id = _add(iid, notes="to delete")
        assert delete_meeting_note(note_id) is True
        assert not any(n["id"] == note_id for n in get_notes_for_intern(iid))

    def test_delete_nonexistent_returns_false(self):
        assert delete_meeting_note("00000000-0000-0000-0000-000000000000") is False

    def test_delete_only_removes_target(self):
        iid = _uid()
        keep_id = _add(iid, notes="keep")
        del_id = _add(iid, notes="delete me")
        delete_meeting_note(del_id)
        ids = {n["id"] for n in get_notes_for_intern(iid)}
        assert keep_id in ids and del_id not in ids


# ── update_meeting_note ───────────────────────────────────────────────────────


class TestUpdateMeetingNote:
    def test_update_fields(self):
        iid = _uid()
        note_id = _add(iid, notes="original", action_items="", visibility="all", week_number=1)
        update_meeting_note(
            note_id,
            notes="updated",
            action_items="- new item",
            visibility="mentor_admin",
            meeting_date="2026-06-20",
            week_number=2,
        )
        updated = next(n for n in get_notes_for_intern(iid, visibility=None) if n["id"] == note_id)
        assert updated["notes"] == "updated"
        assert updated["action_items"] == "- new item"
        assert updated["visibility"] == "mentor_admin"
        assert updated["week_number"] == 2

    def test_update_nonexistent_returns_false(self):
        assert (
            update_meeting_note(
                "00000000-0000-0000-0000-000000000000",
                notes="x",
                action_items="",
                visibility="all",
                meeting_date=None,
                week_number=None,
            )
            is False
        )

    def test_updated_at_changes(self):
        import time

        iid = _uid()
        note_id = _add(iid)
        before = next(n for n in get_notes_for_intern(iid) if n["id"] == note_id)["updated_at"]
        time.sleep(0.01)
        update_meeting_note(
            note_id,
            notes="changed",
            action_items="",
            visibility="all",
            meeting_date=None,
            week_number=None,
        )
        after = next(n for n in get_notes_for_intern(iid, visibility=None) if n["id"] == note_id)[
            "updated_at"
        ]
        assert after >= before
