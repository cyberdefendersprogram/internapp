"""Onboarding routes for new intern profile setup."""

import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import RequiredSession, templates
from app.services.email import send_email
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter()

ONBOARDING_FIELDS = [
    {
        "key": "preferred_name",
        "label": "Preferred Name",
        "type": "text",
        "placeholder": "What should we call you?",
        "help": "This is how you'll appear in the intern portal.",
    },
    {
        "key": "school",
        "label": "School / College",
        "type": "text",
        "placeholder": "e.g., UC Berkeley, Stanford",
        "help": "Your current school or college.",
    },
    {
        "key": "year",
        "label": "Year",
        "type": "select",
        "options": [
            {"value": "", "label": "-- Select --"},
            {"value": "Freshman", "label": "Freshman"},
            {"value": "Sophomore", "label": "Sophomore"},
            {"value": "Junior", "label": "Junior"},
            {"value": "Senior", "label": "Senior"},
            {"value": "Grad", "label": "Graduate Student"},
        ],
        "help": "Your current year in school.",
    },
    {
        "key": "linkedin",
        "label": "LinkedIn Profile URL",
        "type": "url",
        "placeholder": "https://linkedin.com/in/yourprofile",
        "help": "Optional. Share your professional profile.",
    },
    {
        "key": "github",
        "label": "GitHub Profile URL",
        "type": "url",
        "placeholder": "https://github.com/yourusername",
        "help": "Optional. Share your GitHub.",
    },
    {
        "key": "bio",
        "label": "Short Bio",
        "type": "textarea",
        "placeholder": "Tell us about yourself in 2-3 sentences.",
        "help": "Optional. This may appear on the public program dashboard.",
    },
]


def get_fields_to_show(intern) -> list[dict]:
    """Get only the fields that are empty for this intern."""
    empty_fields = intern.get_empty_profile_fields()
    return [f for f in ONBOARDING_FIELDS if f["key"] in empty_fields]


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_form(request: Request, session: RequiredSession):
    """Render the onboarding form."""
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_id(session.intern_id)

    if not intern:
        logger.warning("Intern not found for session: %s", session.intern_id)
        return RedirectResponse(url="/auth/logout", status_code=302)

    if intern.onboarding_completed_at:
        return RedirectResponse(url="/home", status_code=302)

    fields_to_show = get_fields_to_show(intern)

    return templates.TemplateResponse(
        "onboarding.html",
        {
            "request": request,
            "intern": intern,
            "fields": fields_to_show,
            "error": None,
        },
    )


@router.post("/onboarding", response_class=HTMLResponse)
async def onboarding_submit(
    request: Request,
    session: RequiredSession,
    preferred_name: str = Form(""),
    school: str = Form(""),
    year: str = Form(""),
    linkedin: str = Form(""),
    github: str = Form(""),
    bio: str = Form(""),
):
    """Process onboarding form submission."""
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_id(session.intern_id)

    if not intern:
        logger.warning("Intern not found for session: %s", session.intern_id)
        return RedirectResponse(url="/auth/logout", status_code=302)

    field_values = {
        "preferred_name": preferred_name.strip(),
        "school": school.strip(),
        "year": year.strip(),
        "linkedin": linkedin.strip(),
        "github": github.strip(),
        "bio": bio.strip(),
    }

    form_data = {k: v for k, v in field_values.items() if v}

    now = datetime.utcnow().isoformat()
    update_fields = {**form_data, "onboarding_completed_at": now}
    success = sheets.update_roster(session.intern_id, **update_fields)

    if not success:
        logger.error("Failed to update roster %s during onboarding", session.intern_id)
        fields_to_show = get_fields_to_show(intern)
        return templates.TemplateResponse(
            "onboarding.html",
            {
                "request": request,
                "intern": intern,
                "fields": fields_to_show,
                "error": "An error occurred. Please try again.",
            },
        )

    # Send welcome email (best-effort)
    if session.email:
        try:
            from app.config import settings  # noqa: PLC0415

            name = form_data.get("preferred_name") or intern.display_name
            welcome_link = f"{settings.base_url}/home"
            welcome_html = f"""
            <html><body style="font-family:Lato,system-ui,sans-serif;max-width:600px;margin:0 auto;padding:20px;">
            <div style="background:#062F49;padding:20px;border-radius:8px 8px 0 0;">
              <h1 style="color:#fff;font-family:'Roboto Mono',monospace;margin:0;">Welcome to CDP, {name}!</h1>
            </div>
            <div style="background:#fff;padding:24px;border:1px solid #eee;border-radius:0 0 8px 8px;">
              <p>You've successfully completed onboarding for the Cyber Defenders Program internship.</p>
              <p>You can now access your intern dashboard to submit check-ins, deliverables, and update your profile.</p>
              <p style="text-align:center;margin:32px 0;">
                <a href="{welcome_link}" style="background:#FA7C91;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:700;">
                  Go to Dashboard
                </a>
              </p>
            </div>
            </body></html>
            """
            await send_email(session.email, "Welcome to the Cyber Defenders Program!", welcome_html)
        except Exception as e:
            logger.warning("Failed to send welcome email: %s", e)

    logger.info("Onboarding completed for intern %s", session.intern_id)
    return RedirectResponse(url="/home", status_code=302)
