"""Authentication routes for magic link login."""

import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.dependencies import templates
from app.services.email import send_magic_link_email
from app.services.sessions import (
    COOKIE_NAME,
    create_session_token,
    get_cookie_settings,
    verify_session_token,
)
from app.services.sheets import get_sheets_client
from app.services.tokens import check_rate_limit, create_magic_token, validate_magic_token

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def signin_page(request: Request):
    """Render the sign-in page."""
    session_token = request.cookies.get(COOKIE_NAME)
    if session_token:
        session = verify_session_token(session_token)
        if session:
            if session.role == "admin":
                return RedirectResponse(url="/admin", status_code=302)
            elif session.role == "mentor":
                return RedirectResponse(url="/admin/applicants", status_code=302)
            elif session.role == "sponsor":
                return RedirectResponse(url="/sponsor", status_code=302)
            else:
                return RedirectResponse(url="/home", status_code=302)

    return templates.TemplateResponse(
        "signin.html",
        {"request": request, "error": None, "success": None},
    )


def _client_ip(request: Request) -> str:
    """Return the real client IP, respecting X-Forwarded-For from the Nginx proxy."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_registered(email: str, sheets) -> bool:
    """Return True if the email belongs to a known admin, roster member, or sponsor."""
    if email in settings.admin_email_list:
        return True
    if sheets.get_roster_by_email(email):
        return True
    if sheets.get_track_by_sponsor_email(email):
        return True
    return False


_GENERIC_SUCCESS = (
    "If this email is registered, you'll receive a sign-in link shortly. Check your inbox."
)


@router.post("/auth/request-link")
async def request_magic_link(request: Request, email: str = Form(...)):
    """
    Request a magic link email.

    Returns same response for known/unknown emails to prevent enumeration.
    Silently drops requests from emails not in the roster/admin/sponsor lists.
    """
    email = email.strip().lower()
    ip = _client_ip(request)
    sheets = get_sheets_client()

    # Rate limit check (10 per email per 15 min)
    allowed, count = check_rate_limit(email)
    if not allowed:
        logger.warning(
            "Rate limited magic link request for %s from %s (count: %d)", email, ip, count
        )
        sheets.append_magic_link_request(
            {
                "requested_at": datetime.utcnow().isoformat(),
                "email": email,
                "ip_address": ip,
                "result": "rate_limited",
                "note": f"Count: {count}",
            }
        )
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "Too many requests. Please try again in 15 minutes.",
                "success": None,
            },
        )

    # Roster gate — don't send or create a token for unrecognised emails
    if not _is_registered(email, sheets):
        logger.warning("Magic link request from unregistered email %s (ip: %s)", email, ip)
        sheets.append_magic_link_request(
            {
                "requested_at": datetime.utcnow().isoformat(),
                "email": email,
                "ip_address": ip,
                "result": "not_in_roster",
                "note": "",
            }
        )
        return templates.TemplateResponse(
            "signin.html",
            {"request": request, "error": None, "success": _GENERIC_SUCCESS},
        )

    # Create magic token and send
    token = create_magic_token(email)
    magic_link = f"{settings.base_url}/auth/verify?token={token}"
    result = await send_magic_link_email(email, magic_link)

    sheets.append_magic_link_request(
        {
            "requested_at": datetime.utcnow().isoformat(),
            "email": email,
            "ip_address": ip,
            "result": "sent" if result.success else "error",
            "note": result.error or "",
        }
    )

    if not result.success:
        logger.error("Failed to send magic link to %s: %s", email, result.error)

    logger.info("Magic link requested for %s from %s", email, ip)
    return templates.TemplateResponse(
        "signin.html",
        {"request": request, "error": None, "success": _GENERIC_SUCCESS},
    )


@router.get("/auth/verify")
async def verify_magic_link(request: Request, token: str, response: Response):
    """
    Verify magic link token and create session, redirecting by role.

    Priority:
    1. Admin email (ADMIN_EMAILS env var) → role=admin → /admin
    2. Sponsor email (Tracks sheet sponsor_email) → role=sponsor → /sponsor
    3. Intern email already claimed → role=intern → /home (or /onboarding)
    4. Email not found → /claim flow
    """
    email = validate_magic_token(token)
    if not email:
        logger.warning("Invalid or expired magic link")
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "This link is invalid or has expired. Please request a new one.",
                "success": None,
            },
        )

    sheets = get_sheets_client()
    cookie_settings = get_cookie_settings()

    def _make_resp(role: str, intern_id: str, redirect_url: str):
        token = create_session_token(email, intern_id, role)
        r = RedirectResponse(url=redirect_url, status_code=302)
        r.set_cookie(value=token, **cookie_settings)
        return r

    # 1. ADMIN_EMAILS env var — bootstrap escape hatch, always works
    if email in settings.admin_email_list:
        logger.info("Admin login (env): %s", email)
        return _make_resp("admin", "", "/admin")

    # 2. Check Roster for role-tagged entries (admin / mentor / intern)
    roster_entry = sheets.get_roster_by_email(email)
    if roster_entry:
        if roster_entry.role == "admin":
            sheets.update_roster(
                roster_entry.intern_id, last_login_at=datetime.utcnow().isoformat()
            )
            logger.info("Admin login (roster): %s", email)
            return _make_resp("admin", roster_entry.intern_id, "/admin")

        if roster_entry.role == "mentor":
            sheets.update_roster(
                roster_entry.intern_id, last_login_at=datetime.utcnow().isoformat()
            )
            logger.info("Mentor login: %s (track: %s)", email, roster_entry.track_id)
            return _make_resp("mentor", roster_entry.intern_id, "/admin/applicants")

        if roster_entry.is_claimed:
            sheets.update_roster(
                roster_entry.intern_id, last_login_at=datetime.utcnow().isoformat()
            )
            redirect_url = "/home" if roster_entry.is_onboarded else "/onboarding"
            logger.info("Intern login: %s (id: %s)", email, roster_entry.intern_id)
            return _make_resp("intern", roster_entry.intern_id, redirect_url)

        # Email pre-populated by admin but claim never completed — auto-complete it
        if roster_entry.role == "intern" and roster_entry.preferred_email:
            sheets.update_roster(
                roster_entry.intern_id,
                claimed_at=datetime.utcnow().isoformat(),
                last_login_at=datetime.utcnow().isoformat(),
            )
            logger.info("Auto-completed claim for %s (id: %s)", email, roster_entry.intern_id)
            return _make_resp("intern", roster_entry.intern_id, "/onboarding")

    # 3. Legacy sponsor check via Tracks sheet sponsor_email
    track = sheets.get_track_by_sponsor_email(email)
    if track:
        logger.info("Sponsor login: %s (track: %s)", email, track.track_id)
        return _make_resp("sponsor", "", "/sponsor")

    # 4. Email not recognised — return error (no claim flow; contact program admin)
    logger.info("Email %s not registered in roster/admin/sponsor", email)
    return templates.TemplateResponse(
        "signin.html",
        {
            "request": request,
            "error": "This email address is not registered in the program. Please contact your program administrator.",
            "success": None,
        },
    )


@router.get("/auth/discord-link")
async def discord_link(request: Request, token: str, discord_id: str):
    """
    Complete Discord identity linking.

    The bot sends the user here after they request /link:
      /auth/discord-link?token=<magic_token>&discord_id=<snowflake>

    Validates the token (proves email ownership), writes discord_id to Roster,
    then renders a simple success/error page the user sees in their browser.
    """

    def _discord_response(success: bool, error: str | None = None, already_linked: bool = False):
        return templates.TemplateResponse(
            "discord_linked.html",
            {
                "request": request,
                "success": success,
                "error": error,
                "already_linked": already_linked,
            },
        )

    email = validate_magic_token(token)
    if not email:
        return _discord_response(
            False, "This link is invalid or has expired. Run /link again in Discord."
        )

    sheets = get_sheets_client()
    roster_entry = sheets.get_roster_by_email(email)
    if not roster_entry:
        return _discord_response(False, "This email is not registered in the program.")

    if roster_entry.discord_id and roster_entry.discord_id == discord_id:
        return _discord_response(True, already_linked=True)

    ok = sheets.link_discord_id(roster_entry.intern_id, discord_id)
    if not ok:
        return _discord_response(False, "Failed to link your Discord account. Please try again.")

    logger.info("Linked Discord ID %s to intern %s (%s)", discord_id, roster_entry.intern_id, email)
    return _discord_response(True)


@router.post("/auth/logout")
async def logout(request: Request):
    """Log out the current user."""
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    logger.info("User logged out")
    return response


@router.get("/auth/logout")
async def logout_get(request: Request):
    """GET version of logout for convenience."""
    return await logout(request)
