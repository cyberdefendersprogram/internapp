"""Admin routes."""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.dependencies import AdminSession, templates
from app.routers.intern import compute_week_number
from app.services.email import send_email
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

# Email templates directory
EMAIL_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "content" / "emails"


def get_email_template_env() -> Environment:
    """Get Jinja2 environment pointed at content/emails/."""
    return Environment(loader=FileSystemLoader(str(EMAIL_TEMPLATES_DIR)))


@router.get("", response_class=HTMLResponse)
async def admin_home(request: Request, session: AdminSession):
    """All interns table with week status."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    all_interns = sheets.get_all_roster()
    tracks = {t.track_id: t for t in sheets.get_all_tracks()}

    intern_rows = []
    for intern in all_interns:
        checkins = sheets.get_checkins_for_intern(intern.intern_id)
        # Build weekly status dict: {week: True/False}
        weekly_status = {}
        for c in checkins:
            wn = c.get("week_number")
            if wn:
                weekly_status[int(wn)] = True

        track = tracks.get(intern.track_id)
        intern_rows.append(
            {
                "intern": intern,
                "track": track,
                "weekly_status": weekly_status,
                "deliverable_count": len(sheets.get_deliverables_for_intern(intern.intern_id)),
            }
        )

    # Get total weeks from config
    total_weeks = int(sheets.get_config("program_weeks") or 6)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "intern_rows": intern_rows,
            "week_number": week_number,
            "total_weeks": total_weeks,
            "total_interns": len(all_interns),
            "claimed_interns": sum(1 for i in all_interns if i.is_claimed),
        },
    )


@router.get("/intern/{intern_id}", response_class=HTMLResponse)
async def admin_intern_detail(request: Request, intern_id: str, session: AdminSession):
    """Full intern detail view."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    intern = sheets.get_roster_by_id(intern_id)
    if not intern:
        return HTMLResponse("Intern not found.", status_code=404)

    track = sheets.get_track_by_id(intern.track_id)
    checkins = sheets.get_checkins_for_intern(intern_id)
    deliverables = sheets.get_deliverables_for_intern(intern_id)
    feedback_list = sheets.get_feedback_for_intern(intern_id)

    return templates.TemplateResponse(
        "admin_intern.html",
        {
            "request": request,
            "intern": intern,
            "track": track,
            "checkins": sorted(checkins, key=lambda c: c.get("submitted_at", ""), reverse=True),
            "deliverables": sorted(
                deliverables, key=lambda d: d.get("submitted_at", ""), reverse=True
            ),
            "feedback_list": feedback_list,
            "week_number": week_number,
        },
    )


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(request: Request, session: AdminSession):
    """Attendance log and entry form."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    attendance = sheets.get_attendance()
    all_interns = sheets.get_all_roster()
    claimed_interns = [i for i in all_interns if i.is_claimed]

    return templates.TemplateResponse(
        "admin_attendance.html",
        {
            "request": request,
            "attendance": sorted(attendance, key=lambda a: a.get("session_date", ""), reverse=True),
            "interns": claimed_interns,
            "week_number": week_number,
            "error": None,
            "success": None,
        },
    )


@router.post("/attendance", response_class=HTMLResponse)
async def attendance_submit(
    request: Request,
    session: AdminSession,
    session_date: str = Form(...),
    session_type: str = Form(...),
    intern_id: str = Form(...),
    present: str = Form("FALSE"),
    notes: str = Form(""),
):
    """Log attendance."""
    sheets = get_sheets_client()

    data = {
        "session_date": session_date,
        "session_type": session_type,
        "intern_id": intern_id,
        "present": "TRUE" if present in ("true", "TRUE", "1", "on") else "FALSE",
        "notes": notes.strip(),
    }

    sheets.append_attendance(data)
    logger.info("Attendance logged: %s on %s", intern_id, session_date)

    return RedirectResponse(url="/admin/attendance?submitted=1", status_code=302)


@router.get("/email", response_class=HTMLResponse)
async def email_composer(request: Request, session: AdminSession):
    """Email composer with audience picker and template picker."""
    sheets = get_sheets_client()
    all_interns = sheets.get_all_roster()
    tracks = sheets.get_all_tracks()

    # List available templates
    templates_available = []
    if EMAIL_TEMPLATES_DIR.exists():
        templates_available = [p.stem for p in EMAIL_TEMPLATES_DIR.glob("*.html")]

    return templates.TemplateResponse(
        "admin_email.html",
        {
            "request": request,
            "interns": [i for i in all_interns if i.is_claimed],
            "tracks": tracks,
            "email_templates": templates_available,
            "preview_html": None,
            "error": None,
            "success": None,
        },
    )


@router.post("/email/preview")
async def email_preview(
    request: Request,
    session: AdminSession,
    audience: str = Form("all"),
    template_slug: str = Form("welcome"),
    track_id: str = Form(""),
    intern_id: str = Form(""),
    custom_subject: str = Form(""),
    custom_body: str = Form(""),
):
    """Render preview HTML for one sample recipient."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    config = sheets.get_all_config()
    program_title = config.get("program_title", "Cyber Defenders Program")

    # Pick a sample recipient
    all_interns = sheets.get_all_roster()
    claimed = [i for i in all_interns if i.is_claimed]
    sample = claimed[0] if claimed else None

    if not sample:
        return JSONResponse({"preview": "<p>No claimed interns found for preview.</p>"})

    track = sheets.get_track_by_id(sample.track_id)

    ctx = {
        "intern_name": sample.display_name,
        "track_name": track.name if track else "",
        "sponsor_name": track.employer_sponsor if track else "",
        "week_number": week_number,
        "checkin_url": f"{settings.base_url}/checkin",
        "deliverables_url": f"{settings.base_url}/deliverables",
        "program_title": program_title,
        "base_url": settings.base_url,
    }

    if template_slug == "custom":
        preview_html = custom_body
    else:
        try:
            env = get_email_template_env()
            tmpl = env.get_template(f"{template_slug}.html")
            preview_html = tmpl.render(**ctx)
        except Exception as e:
            preview_html = f"<p>Template error: {e}</p>"

    return JSONResponse({"preview": preview_html})


@router.post("/email/send")
async def email_send(
    request: Request,
    session: AdminSession,
    audience: str = Form("all"),
    template_slug: str = Form("welcome"),
    track_id: str = Form(""),
    intern_id_single: str = Form(""),
    custom_subject: str = Form(""),
    custom_body: str = Form(""),
):
    """Send emails and log results. Returns JSON summary."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    config = sheets.get_all_config()
    program_title = config.get("program_title", "Cyber Defenders Program")

    all_interns = sheets.get_all_roster()
    # Build recipient list based on audience
    if audience == "all":
        recipients = [i for i in all_interns if i.is_claimed]
    elif audience == "track" and track_id:
        recipients = [i for i in all_interns if i.is_claimed and i.track_id == track_id]
    elif audience == "missing_checkin":
        # Load checkins for current week
        recipients = []
        for intern in all_interns:
            if not intern.is_claimed:
                continue
            checkins = sheets.get_checkins_for_intern(intern.intern_id)
            checked_in = any(str(c.get("week_number")) == str(week_number) for c in checkins)
            if not checked_in:
                recipients.append(intern)
    elif audience == "single" and intern_id_single:
        intern = sheets.get_roster_by_id(intern_id_single)
        recipients = [intern] if intern and intern.is_claimed else []
    else:
        recipients = [i for i in all_interns if i.is_claimed]

    # Cap at 50
    recipients = recipients[:50]

    sent = 0
    failed = 0

    for intern in recipients:
        track = sheets.get_track_by_id(intern.track_id)
        ctx = {
            "intern_name": intern.display_name,
            "track_name": track.name if track else "",
            "sponsor_name": track.employer_sponsor if track else "",
            "week_number": week_number,
            "checkin_url": f"{settings.base_url}/checkin",
            "deliverables_url": f"{settings.base_url}/deliverables",
            "program_title": program_title,
            "base_url": settings.base_url,
        }

        if template_slug == "custom":
            subject = custom_subject or "Message from Cyber Defenders Program"
            html_body = custom_body
        else:
            try:
                env = get_email_template_env()
                tmpl = env.get_template(f"{template_slug}.html")
                html_body = tmpl.render(**ctx)
                subject = {
                    "welcome": f"Welcome to {program_title}",
                    "weekly-reminder": f"Week {week_number} check-in is open",
                    "missing-checkin": f"Don't forget your Week {week_number} check-in",
                }.get(template_slug, custom_subject or "Message from CDP")
            except Exception as e:
                logger.error("Template render error: %s", e)
                failed += 1
                sheets.append_email_log(
                    {
                        "sent_at": datetime.utcnow().isoformat(),
                        "sender_email": session.email,
                        "recipient_email": intern.preferred_email or "",
                        "recipient_name": intern.display_name,
                        "subject": "",
                        "template": template_slug,
                        "status": "failed",
                        "note": str(e),
                    }
                )
                continue

        result = await send_email(intern.preferred_email or "", subject, html_body)

        log_data = {
            "sent_at": datetime.utcnow().isoformat(),
            "sender_email": session.email,
            "recipient_email": intern.preferred_email or "",
            "recipient_name": intern.display_name,
            "subject": subject,
            "template": template_slug,
            "status": "sent" if result.success else "failed",
            "note": result.error or "",
        }
        sheets.append_email_log(log_data)

        if result.success:
            sent += 1
        else:
            failed += 1

    logger.info("Bulk email sent by %s: %d sent, %d failed", session.email, sent, failed)
    return JSONResponse({"sent": sent, "failed": failed, "total": len(recipients)})
