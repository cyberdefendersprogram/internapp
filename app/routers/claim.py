"""Claim routes for new intern account binding."""

import logging

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import templates
from app.services.sessions import create_session_token, get_cookie_settings
from app.services.sheets import get_sheets_client
from app.services.tokens import validate_magic_token

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/claim", response_class=HTMLResponse)
async def claim_form(request: Request, token: str):
    """
    Render the claim form.

    Requires a valid token from the magic link flow.
    """
    email = validate_magic_token(token)

    if not email:
        logger.warning("Invalid or expired claim token")
        return templates.TemplateResponse(
            "signin.html",
            {
                "request": request,
                "error": "This link is invalid or has expired. Please request a new sign-in link.",
                "success": None,
            },
        )

    return templates.TemplateResponse(
        "claim.html",
        {
            "request": request,
            "email": email,
            "error": None,
        },
    )


@router.post("/claim", response_class=HTMLResponse)
async def claim_submit(
    request: Request,
    response: Response,
    email: str = Form(...),
    intern_id: str = Form(...),
):
    """
    Process account claim.

    Binds the email to the intern account if intern_id exists and is unclaimed.
    """
    email = email.strip().lower()
    intern_id = intern_id.strip()

    sheets = get_sheets_client()

    # Look up intern by ID
    intern = sheets.get_roster_by_id(intern_id)

    if not intern:
        logger.warning("Claim attempt for non-existent intern: %s", intern_id)
        return templates.TemplateResponse(
            "claim.html",
            {
                "request": request,
                "email": email,
                "error": "Invalid intern ID. Please check your information and try again.",
            },
        )

    if intern.is_claimed:
        logger.warning("Claim attempt for already claimed intern: %s", intern_id)
        return templates.TemplateResponse(
            "claim.html",
            {
                "request": request,
                "email": email,
                "error": "This intern account has already been claimed. If this is your account, try signing in with your email.",
            },
        )

    # Claim the account
    success = sheets.claim_intern(intern_id, email)

    if not success:
        logger.error("Failed to claim intern %s", intern_id)
        return templates.TemplateResponse(
            "claim.html",
            {
                "request": request,
                "email": email,
                "error": "An error occurred while claiming your account. Please try again.",
            },
        )

    # Create session
    session_token = create_session_token(email, intern_id, "intern")

    # Redirect to onboarding
    response = RedirectResponse(url="/onboarding", status_code=302)
    cookie_settings = get_cookie_settings()
    response.set_cookie(value=session_token, **cookie_settings)

    logger.info("Intern %s claimed by %s", intern_id, email)
    return response
