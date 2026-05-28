"""Session management using JWT tokens."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# JWT configuration
ALGORITHM = "HS256"
SESSION_TTL_DAYS = 7
COOKIE_NAME = "session"


@dataclass
class SessionData:
    """Decoded session data."""

    email: str
    intern_id: str
    role: str  # "intern", "admin", or "sponsor"
    exp: datetime


def create_session_token(email: str, intern_id: str, role: str) -> str:
    """
    Create a JWT session token.

    Args:
        email: User email
        intern_id: Intern ID (or empty string for admin/sponsor)
        role: One of "intern", "admin", "sponsor"

    Returns:
        Encoded JWT token
    """
    expires = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
    payload = {
        "email": email,
        "intern_id": intern_id,
        "role": role,
        "exp": expires,
    }

    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    logger.info("Created session for %s (intern: %s, role: %s)", email, intern_id, role)
    return token


def verify_session_token(token: str) -> SessionData | None:
    """
    Verify and decode a JWT session token.

    Returns:
        SessionData if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])

        return SessionData(
            email=payload["email"],
            intern_id=payload.get("intern_id", ""),
            role=payload.get("role", "intern"),
            exp=datetime.fromtimestamp(payload["exp"]),
        )
    except JWTError as e:
        logger.warning("Invalid session token: %s", e)
        return None
    except KeyError as e:
        logger.warning("Malformed session token, missing key: %s", e)
        return None


def get_cookie_settings() -> dict:
    """Get cookie settings for session cookie."""
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "secure": not settings.is_development,
        "samesite": "lax",
        "max_age": SESSION_TTL_DAYS * 24 * 60 * 60,  # seconds
    }
