"""Magic token service for passwordless authentication."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from app.config import settings
from app.db.sqlite import get_db

logger = logging.getLogger(__name__)


def create_magic_token(email: str, ttl_minutes: int | None = None) -> str:
    """
    Create a new magic token for an email address.

    Args:
        email: Email address to create token for
        ttl_minutes: Token TTL in minutes (defaults to settings value)

    Returns:
        The raw token (to be sent in magic link)
    """
    if ttl_minutes is None:
        ttl_minutes = settings.magic_link_ttl_minutes

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    now = datetime.utcnow()
    expires_at = now + timedelta(minutes=ttl_minutes)

    with get_db() as db:
        db.execute(
            """
            INSERT INTO magic_tokens (token_hash, email, created_at, expires_at, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (token_hash, email.lower(), now.isoformat(), expires_at.isoformat()),
        )

    logger.info("Created magic token for %s (expires %s)", email, expires_at.isoformat())
    return token


def validate_magic_token(token: str) -> str | None:
    """
    Validate a magic token and mark it as used.

    Args:
        token: Raw token from magic link

    Returns:
        Email address if valid, None otherwise
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    with get_db() as db:
        row = db.execute(
            """
            SELECT email, expires_at, status FROM magic_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if not row:
            logger.warning("Token not found")
            return None

        if row["status"] != "pending":
            logger.warning("Token already used or expired (status: %s)", row["status"])
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at < datetime.utcnow():
            db.execute(
                "UPDATE magic_tokens SET status = 'expired' WHERE token_hash = ?",
                (token_hash,),
            )
            logger.warning("Token expired")
            return None

        # Mark as used
        db.execute(
            """
            UPDATE magic_tokens SET status = 'used', used_at = ?
            WHERE token_hash = ?
            """,
            (datetime.utcnow().isoformat(), token_hash),
        )

        logger.info("Magic token validated for %s", row["email"])
        return row["email"]


def check_rate_limit(email: str) -> tuple[bool, int]:
    """
    Check if an email is rate limited.

    Args:
        email: Email address to check

    Returns:
        Tuple of (is_allowed, current_count)
    """
    key = f"magic:{email.lower()}"
    max_requests = settings.rate_limit_per_email_15m  # default 10
    window_minutes = 15

    now = datetime.utcnow()
    window_start = now - timedelta(minutes=window_minutes)

    with get_db() as db:
        row = db.execute(
            "SELECT window_start, count FROM rate_limits WHERE key = ?",
            (key,),
        ).fetchone()

        if row is None:
            db.execute(
                "INSERT INTO rate_limits (key, window_start, count) VALUES (?, ?, 1)",
                (key, now.isoformat()),
            )
            return True, 1

        record_window_start = datetime.fromisoformat(row["window_start"])

        if record_window_start < window_start:
            db.execute(
                "UPDATE rate_limits SET window_start = ?, count = 1 WHERE key = ?",
                (now.isoformat(), key),
            )
            return True, 1

        current_count = row["count"]
        if current_count >= max_requests:
            logger.warning("Rate limit exceeded for %s (count: %d)", email, current_count)
            return False, current_count

        db.execute(
            "UPDATE rate_limits SET count = count + 1 WHERE key = ?",
            (key,),
        )
        return True, current_count + 1


def cleanup_expired_tokens() -> int:
    """
    Clean up expired tokens from the database.

    Returns:
        Number of tokens cleaned up
    """
    with get_db() as db:
        now = datetime.utcnow().isoformat()
        cursor = db.execute(
            """
            UPDATE magic_tokens
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at < ?
            """,
            (now,),
        )
        expired_count = cursor.rowcount

        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        cursor = db.execute(
            "DELETE FROM magic_tokens WHERE created_at < ?",
            (cutoff,),
        )
        deleted_count = cursor.rowcount

        if expired_count or deleted_count:
            logger.info("Token cleanup: %d expired, %d deleted", expired_count, deleted_count)

        return expired_count + deleted_count
