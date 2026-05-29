"""Admin/mentor applicant interview routes."""

import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.dependencies import AdminOrMentorSession, AdminSession, templates
from app.services.email import send_email
from app.services.sheets import SheetsUnavailableError, get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/applicants")

EMAIL_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "content" / "emails"


def _render_welcome(ctx: dict) -> str:
    env = Environment(loader=FileSystemLoader(str(EMAIL_TEMPLATES_DIR)))
    return env.get_template("welcome.html").render(**ctx)


@router.get("", response_class=HTMLResponse)
async def applicants_list(request: Request, session: AdminOrMentorSession):
    if not settings.applicant_sheets_id:
        return HTMLResponse(
            "<p>APPLICANT_SHEETS_ID is not configured. Add it to your .env file.</p>",
            status_code=503,
        )
    sheets = get_sheets_client()
    try:
        applicants = sheets.get_all_applicants()
    except SheetsUnavailableError:
        raise HTTPException(
            status_code=503, detail="Sheets temporarily unavailable — please retry in a moment."
        )

    feedback_counts = sheets.get_all_applicant_feedback_counts()

    return templates.TemplateResponse(
        "admin_applicants.html",
        {
            "request": request,
            "applicants": applicants,
            "feedback_counts": feedback_counts,
            "session": session,
        },
    )


@router.get("/{row_index}", response_class=HTMLResponse)
async def applicant_interview(request: Request, row_index: int, session: AdminOrMentorSession):
    sheets = get_sheets_client()
    try:
        applicant = sheets.get_applicant_by_row(row_index)
    except SheetsUnavailableError:
        raise HTTPException(
            status_code=503, detail="Sheets temporarily unavailable — please retry in a moment."
        )
    if not applicant:
        return HTMLResponse("Applicant not found.", status_code=404)

    all_feedback = sheets.get_applicant_feedback(row_index)
    my_feedback = next(
        (
            f.get("feedback", "")
            for f in all_feedback
            if f.get("reviewer_email", "").lower() == session.email.lower()
        ),
        "",
    )
    others_feedback = [
        f for f in all_feedback if f.get("reviewer_email", "").lower() != session.email.lower()
    ]

    tracks = sheets.get_all_tracks() if session.role == "admin" else []
    next_intern_id = sheets._next_intern_id() if session.role == "admin" else ""

    flash = request.query_params.get("flash", "")
    return templates.TemplateResponse(
        "admin_applicant_interview.html",
        {
            "request": request,
            "applicant": applicant,
            "my_feedback": my_feedback,
            "others_feedback": others_feedback,
            "feedback_count": len(all_feedback),
            "tracks": tracks,
            "next_intern_id": next_intern_id,
            "flash": flash,
            "session": session,
        },
    )


@router.post("/{row_index}/feedback")
async def save_feedback(
    request: Request,
    row_index: int,
    session: AdminOrMentorSession,
    feedback: str = Form(""),
    decision: str = Form("Pending"),
):
    sheets = get_sheets_client()

    roster = sheets.get_roster_by_email(session.email)
    reviewer_name = roster.display_name if roster else session.email

    if feedback.strip():
        sheets.upsert_applicant_feedback(
            applicant_row=row_index,
            reviewer_email=session.email,
            reviewer_name=reviewer_name,
            feedback=feedback.strip(),
        )

    if session.role == "admin" and decision in ("Pending", "Accept", "Waitlist", "Decline"):
        sheets.save_decision(row_index, decision)

    logger.info(
        "Feedback/decision saved for row %s by %s (decision=%s)", row_index, session.email, decision
    )
    return RedirectResponse(url=f"/admin/applicants/{row_index}?flash=saved", status_code=302)


@router.post("/{row_index}/admit")
async def admit_applicant(
    request: Request,
    row_index: int,
    session: AdminSession,  # admin-only
    track_id: str = Form(...),
    intern_id: str = Form(...),
    send_welcome: str = Form(""),  # checkbox value "1" or ""
):
    sheets = get_sheets_client()
    applicant = sheets.get_applicant_by_row(row_index)
    if not applicant:
        return HTMLResponse("Applicant not found.", status_code=404)

    if applicant.is_admitted:
        return RedirectResponse(
            url=f"/admin/applicants/{row_index}?flash=already_admitted", status_code=302
        )

    ok = sheets.admit_applicant(
        row_index=row_index,
        full_name=applicant.full_name,
        track_id=track_id,
        intern_id=intern_id,
    )
    if not ok:
        return RedirectResponse(
            url=f"/admin/applicants/{row_index}?flash=admit_error", status_code=302
        )

    if send_welcome and applicant.email:
        track = sheets.get_track_by_id(track_id)
        config = sheets.get_all_config()
        program_title = config.get("program_title", "Cyber Defenders Program")
        html_body = _render_welcome(
            {
                "intern_name": applicant.display_name,
                "track_name": track.name if track else "",
                "sponsor_name": track.employer_sponsor if track else "",
                "week_number": int(config.get("program_weeks", "6")),
                "checkin_url": f"{settings.base_url}/checkin",
                "deliverables_url": f"{settings.base_url}/deliverables",
                "program_title": program_title,
                "base_url": settings.base_url,
            }
        )
        result = await send_email(
            applicant.email,
            f"Welcome to {program_title}!",
            html_body,
        )
        flash = "admitted_emailed" if result.success else "admitted_email_failed"
        logger.info(
            "Welcome email to %s: %s", applicant.email, "ok" if result.success else result.error
        )
    else:
        flash = "admitted"

    return RedirectResponse(url=f"/admin/applicants/{row_index}?flash={flash}", status_code=302)
