import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.models.intern import InternEntry

# SQL schema for magic_tokens table
SCHEMA_MAGIC_TOKENS = """
CREATE TABLE IF NOT EXISTS magic_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'used', 'expired'))
);
CREATE INDEX IF NOT EXISTS idx_magic_tokens_email ON magic_tokens(email);
CREATE INDEX IF NOT EXISTS idx_magic_tokens_status ON magic_tokens(status);
"""

# SQL schema for rate_limits table
SCHEMA_RATE_LIMITS = """
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    count INTEGER DEFAULT 1
);
"""

# SQL schema for intern_cache table
SCHEMA_INTERN_CACHE = """
CREATE TABLE IF NOT EXISTS intern_cache (
    intern_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);
"""

SCHEMA_MEETING_NOTES = """
CREATE TABLE IF NOT EXISTS meeting_notes (
    id           TEXT PRIMARY KEY,
    intern_id    TEXT NOT NULL,
    meeting_type TEXT NOT NULL DEFAULT 'mentor_1on1',
    week_number  INTEGER,
    meeting_date TEXT,
    notes        TEXT NOT NULL DEFAULT '',
    action_items TEXT NOT NULL DEFAULT '',
    created_by   TEXT NOT NULL,
    visibility   TEXT NOT NULL DEFAULT 'all',
    created_at   TEXT NOT NULL,
    updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_intern ON meeting_notes(intern_id);
CREATE INDEX IF NOT EXISTS idx_meeting_notes_type   ON meeting_notes(meeting_type);
"""

INTERN_CACHE_TTL_SECONDS = 900  # 15 minutes — reduces Sheets API call frequency


def init_db() -> None:
    """Initialize the SQLite database with required tables."""
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with get_db() as db:
        db.executescript(SCHEMA_MAGIC_TOKENS)
        db.executescript(SCHEMA_RATE_LIMITS)
        db.executescript(SCHEMA_INTERN_CACHE)
        db.executescript(SCHEMA_MEETING_NOTES)


@contextmanager
def get_db():
    """Get a database connection with automatic commit/rollback."""
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def check_db_health() -> bool:
    """Check if the database is accessible and has required tables."""
    try:
        with get_db() as db:
            db.execute("SELECT 1")
            cursor = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
                ("magic_tokens", "rate_limits"),
            )
            tables = [row["name"] for row in cursor.fetchall()]
            return len(tables) == 2
    except Exception:
        return False


def get_cached_intern(
    intern_id: str, max_age_seconds: int = INTERN_CACHE_TTL_SECONDS
) -> "InternEntry | None":
    """Return cached InternEntry if within max_age_seconds, else None."""
    from app.models.intern import InternEntry  # noqa: PLC0415

    try:
        with get_db() as db:
            row = db.execute(
                "SELECT profile_json, cached_at FROM intern_cache WHERE intern_id = ?",
                (intern_id,),
            ).fetchone()
        if not row:
            return None
        cached_at = datetime.fromisoformat(row["cached_at"])
        if datetime.utcnow() - cached_at > timedelta(seconds=max_age_seconds):
            return None
        data = json.loads(row["profile_json"])
        return InternEntry.from_row(data)
    except Exception:
        return None


def set_cached_intern(intern: "InternEntry") -> None:
    """Upsert an InternEntry into the local SQLite cache."""
    import dataclasses

    data = dataclasses.asdict(intern)
    for key, val in data.items():
        if isinstance(val, datetime):
            data[key] = val.isoformat()
    try:
        with get_db() as db:
            db.execute(
                """INSERT INTO intern_cache (intern_id, profile_json, cached_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(intern_id) DO UPDATE SET
                       profile_json = excluded.profile_json,
                       cached_at = excluded.cached_at""",
                (intern.intern_id, json.dumps(data), datetime.utcnow().isoformat()),
            )
    except Exception:
        pass


# ── Meeting notes ─────────────────────────────────────────────────────────────


def add_meeting_note(
    *,
    intern_id: str,
    meeting_type: str,
    week_number: int | None,
    meeting_date: str | None,
    notes: str,
    action_items: str,
    created_by: str,
    visibility: str = "all",
) -> str:
    """Insert a meeting note and return its UUID."""
    note_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO meeting_notes
               (id, intern_id, meeting_type, week_number, meeting_date,
                notes, action_items, created_by, visibility, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note_id,
                intern_id,
                meeting_type,
                week_number,
                meeting_date,
                notes,
                action_items,
                created_by,
                visibility,
                now,
                now,
            ),
        )
    return note_id


def get_notes_for_intern(intern_id: str, visibility: str | None = None) -> list[dict]:
    """Return meeting notes for an intern, newest first.

    If visibility is 'all', only returns notes with visibility='all'.
    If visibility is None, returns all notes (admin/mentor view).
    """
    with get_db() as db:
        if visibility == "all":
            rows = db.execute(
                """SELECT * FROM meeting_notes
                   WHERE intern_id = ? AND visibility = 'all'
                   ORDER BY meeting_date DESC, created_at DESC""",
                (intern_id,),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT * FROM meeting_notes
                   WHERE intern_id = ?
                   ORDER BY meeting_date DESC, created_at DESC""",
                (intern_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_sponsor_notes_for_intern(intern_id: str) -> list[dict]:
    """Return sponsor check-in notes visible to sponsors (visibility=all)."""
    with get_db() as db:
        rows = db.execute(
            """SELECT * FROM meeting_notes
               WHERE intern_id = ? AND meeting_type = 'sponsor_checkin' AND visibility = 'all'
               ORDER BY meeting_date DESC, created_at DESC""",
            (intern_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_meeting_note(note_id: str) -> bool:
    """Delete a meeting note by ID. Returns True if a row was deleted."""
    with get_db() as db:
        cursor = db.execute("DELETE FROM meeting_notes WHERE id = ?", (note_id,))
    return cursor.rowcount > 0


def update_meeting_note(
    note_id: str,
    *,
    notes: str,
    action_items: str,
    visibility: str,
    meeting_date: str | None,
    week_number: int | None,
) -> bool:
    """Update an existing meeting note. Returns True if a row was updated."""
    now = datetime.utcnow().isoformat()
    with get_db() as db:
        cursor = db.execute(
            """UPDATE meeting_notes
               SET notes = ?, action_items = ?, visibility = ?,
                   meeting_date = ?, week_number = ?, updated_at = ?
               WHERE id = ?""",
            (notes, action_items, visibility, meeting_date, week_number, now, note_id),
        )
    return cursor.rowcount > 0
