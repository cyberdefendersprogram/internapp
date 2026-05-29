import json
import sqlite3
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

INTERN_CACHE_TTL_SECONDS = 900  # 15 minutes — reduces Sheets API call frequency


def init_db() -> None:
    """Initialize the SQLite database with required tables."""
    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with get_db() as db:
        db.executescript(SCHEMA_MAGIC_TOKENS)
        db.executescript(SCHEMA_RATE_LIMITS)
        db.executescript(SCHEMA_INTERN_CACHE)


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
