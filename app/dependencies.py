"""Shared dependencies for FastAPI application."""

import logging
from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.sqlite import get_cached_intern, set_cached_intern
from app.models.intern import InternEntry
from app.services.sessions import COOKIE_NAME, SessionData, verify_session_token
from app.services.sheets import SheetsUnavailableError, get_sheets_client

logger = logging.getLogger(__name__)

# Templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_session(
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> SessionData | None:
    """Get current session from cookie. Returns None if no valid session."""
    if not session:
        return None
    return verify_session_token(session)


def require_session(
    session: Annotated[SessionData | None, Depends(get_current_session)],
) -> SessionData:
    """Require a valid session. Raises 401 if no valid session."""
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return session


def get_current_intern(
    session: Annotated[SessionData, Depends(require_session)],
) -> InternEntry:
    """
    Get the current intern from session.

    Checks SQLite cache first to avoid per-request Sheets API calls.
    On cache miss, fetches from Sheets and refreshes cache.
    """
    intern = get_cached_intern(session.intern_id)
    if intern:
        return intern

    sheets = get_sheets_client()
    try:
        intern = sheets.get_roster_by_id(session.intern_id)
    except SheetsUnavailableError:
        stale = get_cached_intern(session.intern_id, max_age_seconds=86400)
        if stale:
            logger.warning("Serving stale cache for %s (Sheets unavailable)", session.intern_id)
            return stale
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again in a moment.",
        )

    if not intern:
        logger.warning("Intern not found for session: %s", session.intern_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Intern not found",
        )

    set_cached_intern(intern)
    return intern


def require_onboarded(
    intern: Annotated[InternEntry, Depends(get_current_intern)],
) -> InternEntry:
    """Require that the intern has completed onboarding."""
    if not intern.onboarding_completed_at:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Onboarding required",
        )
    return intern


def require_admin(
    session: Annotated[SessionData, Depends(require_session)],
) -> SessionData:
    """Require admin role."""
    if session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return session


def require_admin_or_mentor(
    session: Annotated[SessionData, Depends(require_session)],
) -> SessionData:
    """Require admin or mentor role."""
    if session.role not in ("admin", "mentor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or mentor access required",
        )
    return session


def require_sponsor(
    session: Annotated[SessionData, Depends(require_session)],
) -> SessionData:
    """Require sponsor access."""
    if session.role not in ("sponsor", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sponsor access required",
        )
    return session


def require_intern(
    session: Annotated[SessionData, Depends(require_session)],
) -> SessionData:
    """Require intern role."""
    if session.role != "intern":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Intern access required",
        )
    return session


def require_bot_api_key(
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """Require a valid BOT_API_KEY. Accepts X-Api-Key header or Bearer token."""
    if not settings.discord_cdpbot_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Bot API not configured",
        )
    token = x_api_key or ""
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if token != settings.discord_cdpbot_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    return token


# Type aliases for cleaner dependency injection
CurrentSession = Annotated[SessionData | None, Depends(get_current_session)]
RequiredSession = Annotated[SessionData, Depends(require_session)]
CurrentIntern = Annotated[InternEntry, Depends(get_current_intern)]
OnboardedIntern = Annotated[InternEntry, Depends(require_onboarded)]
AdminSession = Annotated[SessionData, Depends(require_admin)]
AdminOrMentorSession = Annotated[SessionData, Depends(require_admin_or_mentor)]
SponsorSession = Annotated[SessionData, Depends(require_sponsor)]
InternSession = Annotated[SessionData, Depends(require_intern)]
BotApiKey = Annotated[str, Depends(require_bot_api_key)]
