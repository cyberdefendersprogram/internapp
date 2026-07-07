"""Admin routes."""

import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader

from app.config import settings
from app.db.sqlite import (
    add_meeting_note,
    delete_meeting_note,
    get_notes_for_intern,
    update_meeting_note,
)
from app.dependencies import AdminOrMentorSession, AdminSession, templates
from app.routers.intern import SURVEY_TITLES, compute_week_number
from app.services.cache import get_cache_stats, invalidate_all
from app.services.email import send_email
from app.services.sheets import SURVEY_SHEET_NAMES, get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

# Email templates directory
EMAIL_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "content" / "emails"


def get_email_template_env() -> Environment:
    """Get Jinja2 environment pointed at content/emails/."""
    return Environment(loader=FileSystemLoader(str(EMAIL_TEMPLATES_DIR)))


@router.get("", response_class=HTMLResponse)
async def admin_home(request: Request, session: AdminSession):
    """Admin dashboard — interns grouped by track, plus mentor/sponsor rosters."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    total_weeks = int(sheets.get_config("program_weeks") or 6)

    all_roster = sheets.get_all_roster()
    tracks_list = sheets.get_all_tracks()
    tracks = {t.track_id: t for t in tracks_list}

    interns = [r for r in all_roster if r.role == "intern"]
    mentors = [r for r in all_roster if r.role == "mentor" or (r.role == "admin" and r.track_id)]
    sponsors = [r for r in all_roster if r.role == "sponsor"]

    # Build intern rows with per-week check-in status
    intern_rows = []
    checked_in_this_week = 0
    for intern in interns:
        checkins = sheets.get_checkins_for_intern(intern.intern_id)
        weekly_status = {}
        for c in checkins:
            wn = c.get("week_number")
            if wn:
                weekly_status[int(wn)] = True
        if weekly_status.get(week_number):
            checked_in_this_week += 1
        track = tracks.get(intern.track_id)
        intern_rows.append(
            {
                "intern": intern,
                "track": track,
                "weekly_status": weekly_status,
                "deliverable_count": 0,  # deliverables now tracked in Linear
            }
        )

    # Group intern rows by track (single track_id only for interns)
    track_groups = {}
    for row in intern_rows:
        tid = row["intern"].track_id or "unassigned"
        if tid not in track_groups:
            track_groups[tid] = {
                "track": row["track"] or tracks.get(tid),
                "track_id": tid,
                "rows": [],
                "mentors": [],
                "sponsors": [],
            }
        track_groups[tid]["rows"].append(row)

    # Attach mentors and sponsors to each of their tracks (multi-track aware)
    for m in mentors:
        for tid in (m.track_ids or [m.track_id]) if m.track_id else []:
            if tid and tid in track_groups:
                track_groups[tid]["mentors"].append(m)
    for s in sponsors:
        for tid in (s.track_ids or [s.track_id]) if s.track_id else []:
            if tid and tid in track_groups:
                track_groups[tid]["sponsors"].append(s)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "track_groups": list(track_groups.values()),
            "mentors": mentors,
            "sponsors": sponsors,
            "tracks": tracks,
            "week_number": week_number,
            "total_weeks": total_weeks,
            "total_interns": len(interns),
            "claimed_interns": sum(1 for i in interns if i.is_claimed),
            "checked_in_this_week": checked_in_this_week,
        },
    )


@router.get("/intern/{intern_id}", response_class=HTMLResponse)
async def admin_intern_detail(
    request: Request,
    intern_id: str,
    session: AdminOrMentorSession,
    note_saved: str = "",
):
    """Full intern detail view (admin and mentor)."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    intern = sheets.get_roster_by_id(intern_id)
    if not intern:
        return HTMLResponse("Intern not found.", status_code=404)

    from app.db.sqlite import get_linear_issues_for_intern  # noqa: PLC0415

    track = sheets.get_track_by_id(intern.track_id)
    checkins = sheets.get_checkins_for_intern(intern_id)
    feedback_list = sheets.get_feedback_for_intern(intern_id)
    meeting_notes = get_notes_for_intern(intern_id)  # all notes for admin/mentor
    linear_issues = get_linear_issues_for_intern(intern_id, max_age_seconds=86400)
    deliverables = sorted(
        [
            i
            for i in linear_issues
            if i.get("linked_feature") == "deliverable" and i["state_type"] == "completed"
        ],
        key=lambda i: i.get("due_week") or 99,
    )

    return templates.TemplateResponse(
        "admin_intern.html",
        {
            "request": request,
            "intern": intern,
            "track": track,
            "checkins": sorted(checkins, key=lambda c: c.get("submitted_at", ""), reverse=True),
            "deliverables": deliverables,
            "feedback_list": feedback_list,
            "meeting_notes": meeting_notes,
            "week_number": week_number,
            "note_saved": note_saved,
            "session_role": session.role,
            "now_date": date.today().isoformat(),
        },
    )


@router.post("/intern/{intern_id}/notes", response_class=HTMLResponse)
async def admin_add_note(
    request: Request,
    intern_id: str,
    session: AdminOrMentorSession,
    meeting_type: str = Form("mentor_1on1"),
    week_number: str = Form(""),
    meeting_date: str = Form(""),
    notes: str = Form(""),
    action_items: str = Form(""),
    visibility: str = Form("all"),
):
    """Add a meeting note for an intern."""
    intern = get_sheets_client().get_roster_by_id(intern_id)
    if not intern:
        return HTMLResponse("Intern not found.", status_code=404)

    add_meeting_note(
        intern_id=intern_id,
        meeting_type=meeting_type,
        week_number=int(week_number) if week_number.strip() else None,
        meeting_date=meeting_date.strip() or None,
        notes=notes.strip(),
        action_items=action_items.strip(),
        created_by=session.email,
        visibility=visibility,
    )
    return RedirectResponse(url=f"/admin/intern/{intern_id}?note_saved=1", status_code=303)


@router.post("/intern/{intern_id}/notes/{note_id}/delete")
async def admin_delete_note(
    intern_id: str,
    note_id: str,
    session: AdminOrMentorSession,
):
    """Delete a meeting note."""
    delete_meeting_note(note_id)
    return RedirectResponse(url=f"/admin/intern/{intern_id}", status_code=303)


@router.post("/intern/{intern_id}/notes/{note_id}/edit")
async def admin_edit_note(
    intern_id: str,
    note_id: str,
    session: AdminOrMentorSession,
    week_number: str = Form(""),
    meeting_date: str = Form(""),
    notes: str = Form(""),
    action_items: str = Form(""),
    visibility: str = Form("all"),
):
    """Update an existing meeting note."""
    update_meeting_note(
        note_id,
        notes=notes.strip(),
        action_items=action_items.strip(),
        visibility=visibility,
        meeting_date=meeting_date.strip() or None,
        week_number=int(week_number) if week_number.strip() else None,
    )
    return RedirectResponse(url=f"/admin/intern/{intern_id}?note_saved=1", status_code=303)


@router.get("/email", response_class=HTMLResponse)
async def email_composer(request: Request, session: AdminSession):
    """Email composer with audience picker and template picker."""
    sheets = get_sheets_client()
    all_interns = sheets.get_all_roster()
    tracks = sheets.get_all_tracks()

    # List available templates — exclude applicant-only templates from intern audiences
    templates_available = []
    if EMAIL_TEMPLATES_DIR.exists():
        templates_available = sorted(p.stem for p in EMAIL_TEMPLATES_DIR.glob("*.html"))

    applicants = sheets.get_all_applicants() if settings.applicant_sheets_id else []
    waitlist_count = sum(1 for a in applicants if a.decision == "Waitlist")
    decline_count = sum(1 for a in applicants if a.decision == "Decline")

    return templates.TemplateResponse(
        "admin_email.html",
        {
            "request": request,
            "interns": [i for i in all_interns if i.is_claimed],
            "tracks": tracks,
            "email_templates": templates_available,
            "waitlist_count": waitlist_count,
            "decline_count": decline_count,
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

    # Applicant-audience templates use applicant context
    if audience in ("waitlist_applicants", "declined_applicants"):
        decision = "Waitlist" if audience == "waitlist_applicants" else "Decline"
        applicants = sheets.get_all_applicants()
        sample_app = next((a for a in applicants if a.decision == decision), None)
        ctx = {
            "intern_name": sample_app.display_name if sample_app else "Sample Applicant",
            "program_title": program_title,
        }
        try:
            env = get_email_template_env()
            tmpl = env.get_template(f"{template_slug}.html")
            preview_html = tmpl.render(**ctx)
        except Exception as e:
            preview_html = f"<p>Template error: {e}</p>"
        return JSONResponse({"preview": preview_html})

    # Intern-audience templates
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

    APPLICANT_AUDIENCES = {"waitlist_applicants", "declined_applicants"}
    APPLICANT_SUBJECTS = {
        "waitlist": f"Your Application to {program_title} — Waitlist Status",
        "waitlist-closed": f"Update on your {program_title} application",
        "decline": f"Thank you for applying to {program_title}",
    }
    INTERN_SUBJECTS = {
        "welcome": f"Welcome to {program_title}",
        "kickoff": f"See you tomorrow — {program_title} Kickoff, Monday 10am PST",
        "confirm-spot": "Action required: confirm your spot by June 17 at 5pm PST",
        "weekly-reminder": f"Week {week_number} check-in is open",
        "missing-checkin": f"Don't forget your Week {week_number} check-in",
    }

    sent = 0
    failed = 0

    # ── Applicant audiences (waitlist / decline) ──────────────────────────────
    if audience in APPLICANT_AUDIENCES:
        decision = "Waitlist" if audience == "waitlist_applicants" else "Decline"
        applicants = sheets.get_all_applicants()
        targets = [a for a in applicants if a.decision == decision and a.email]

        try:
            env = get_email_template_env()
            tmpl = env.get_template(f"{template_slug}.html")
        except Exception as e:
            return JSONResponse({"sent": 0, "failed": 0, "total": 0, "error": str(e)})

        subject = APPLICANT_SUBJECTS.get(
            template_slug, custom_subject or f"Update from {program_title}"
        )

        for applicant in targets:
            ctx = {"intern_name": applicant.display_name, "program_title": program_title}
            try:
                html_body = tmpl.render(**ctx)
            except Exception as e:
                logger.error("Template render error for %s: %s", applicant.email, e)
                failed += 1
                continue

            result = await send_email(applicant.email, subject, html_body)
            sheets.append_email_log(
                {
                    "sent_at": datetime.utcnow().isoformat(),
                    "sender_email": settings.forwardemail_user,
                    "recipient_email": applicant.email,
                    "recipient_name": applicant.display_name,
                    "subject": subject,
                    "template": template_slug,
                    "status": "sent" if result.success else "failed",
                    "note": result.error or "",
                }
            )
            if result.success:
                sent += 1
            else:
                failed += 1

        logger.info(
            "Applicant bulk email (%s) by %s: %d sent, %d failed",
            decision,
            session.email,
            sent,
            failed,
        )
        return JSONResponse({"sent": sent, "failed": failed, "total": len(targets)})

    # ── Intern / roster audiences ─────────────────────────────────────────────
    all_interns = sheets.get_all_roster()
    if audience == "admitted":
        # All interns with an email address — admitted but may not have claimed yet
        recipients = [i for i in all_interns if i.role == "intern" and i.preferred_email]
    elif audience == "not_onboarded":
        # Admitted interns who have not completed onboarding (includes unclaimed)
        recipients = [
            i
            for i in all_interns
            if i.role == "intern" and i.preferred_email and not i.is_onboarded
        ]
    elif audience == "all":
        recipients = [i for i in all_interns if i.is_claimed]
    elif audience == "track" and track_id:
        recipients = [i for i in all_interns if i.is_claimed and i.track_id == track_id]
    elif audience == "missing_checkin":
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

    recipients = recipients[:50]

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
                subject = INTERN_SUBJECTS.get(template_slug, custom_subject or "Message from CDP")
            except Exception as e:
                logger.error("Template render error: %s", e)
                failed += 1
                sheets.append_email_log(
                    {
                        "sent_at": datetime.utcnow().isoformat(),
                        "sender_email": settings.forwardemail_user,
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
            "sender_email": settings.forwardemail_user,
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


@router.get("/intern/{intern_id}/preview", response_class=HTMLResponse)
async def preview_as_intern(request: Request, intern_id: str, session: AdminSession):
    """Render the intern dashboard server-side without touching the session cookie."""
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_id(intern_id)
    if not intern:
        return HTMLResponse("Intern not found.", status_code=404)

    from app.db.sqlite import get_linear_issues_for_intern  # noqa: PLC0415
    from app.services.linear import sync_intern_issues_from_linear  # noqa: PLC0415

    track = sheets.get_track_by_id(intern.track_id)
    week_number = compute_week_number(sheets)
    checkins = sheets.get_checkins_for_intern(intern.intern_id)
    checked_in_this_week = any(str(c.get("week_number")) == str(week_number) for c in checkins)

    linear_tasks = get_linear_issues_for_intern(intern.intern_id, max_age_seconds=86400)
    if not linear_tasks and intern.linear_user_id:
        sync_intern_issues_from_linear(intern.intern_id, intern.linear_user_id)
        linear_tasks = get_linear_issues_for_intern(intern.intern_id)

    todo_tasks = sorted(
        [t for t in linear_tasks if t["state_type"] not in ("completed", "canceled")],
        key=lambda t: t.get("due_week") or 99,
    )
    done_tasks = [t for t in linear_tasks if t["state_type"] == "completed"]

    all_roster = sheets.get_all_roster()
    mentors_with_cal = [r for r in all_roster if r.role in ("mentor", "admin") and r.cal_link]

    logger.info("Admin %s previewing intern dashboard for %s", session.email, intern_id)
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "intern": intern,
            "track": track,
            "week_number": week_number,
            "checked_in_this_week": checked_in_this_week,
            "todo_tasks": todo_tasks,
            "done_tasks": done_tasks,
            "mentor": mentors_with_cal[0] if mentors_with_cal else None,
            "mentors": mentors_with_cal,
            "meeting_notes": [],
            "preview_mode": True,
            "preview_back_url": f"/admin/intern/{intern_id}",
            "session": None,
        },
    )


@router.get("/survey/{survey_type}/preview", response_class=HTMLResponse)
async def preview_survey(request: Request, survey_type: str, session: AdminSession):
    """Render a survey form read-only for admins, who never complete intern onboarding
    and so can't hit the real /survey/{type} route (gated on OnboardedIntern)."""
    if survey_type not in SURVEY_SHEET_NAMES:
        return HTMLResponse("Unknown survey.", status_code=404)

    logger.info("Admin %s previewing survey %s", session.email, survey_type)
    return templates.TemplateResponse(
        "survey.html",
        {
            "request": request,
            "intern": None,
            "survey_type": survey_type,
            "survey_title": SURVEY_TITLES.get(survey_type, "Survey"),
            "response": None,
            "error": None,
            "preview_mode": True,
        },
    )


@router.post("/discord/send-reminders")
async def discord_send_reminders(request: Request, session: AdminSession):
    """Manually trigger check-in reminder DMs — same logic as the Thursday cron job."""
    from app.jobs.reminders import send_checkin_reminders  # noqa: PLC0415

    result = send_checkin_reminders()
    logger.info("Manual reminder trigger by %s: %s", session.email, result)
    return JSONResponse(result)


@router.post("/cache/clear")
async def cache_clear(request: Request, session: AdminSession):
    """Flush the in-memory cache so the next request re-reads from Google Sheets."""
    stats_before = get_cache_stats()
    cleared = invalidate_all()
    logger.info("Cache cleared by %s: %d entries flushed", session.email, cleared)
    return JSONResponse({"cleared": cleared, "before": stats_before})


# ── Linear task management ────────────────────────────────────────────────────


@router.get("/linear", response_class=HTMLResponse)
async def linear_home(request: Request, session: AdminSession):
    """Linear task fan-out management page."""
    from app.db.sqlite import get_linear_issues_for_intern  # noqa: PLC0415

    sheets = get_sheets_client()
    all_roster = sheets.get_all_roster()
    interns = [r for r in all_roster if r.role == "intern" and r.preferred_email]
    tracks = {t.track_id: t for t in sheets.get_all_tracks()}

    ws = sheets._get_worksheet("Task_Templates")
    task_templates = ws.get_all_records()

    intern_rows = []
    for intern in interns:
        issues = get_linear_issues_for_intern(intern.intern_id, max_age_seconds=86400)
        track = tracks.get(intern.track_id)
        intern_rows.append(
            {
                "intern": intern,
                "track": track,
                "issue_count": len(issues),
                "has_project_id": bool(track and track.linear_project_id),
                "has_linear_user": bool(intern.linear_user_id),
            }
        )

    # Group templates by week for the UI
    weeks = sorted({int(t["due_week"]) for t in task_templates if t.get("due_week")})
    templates_by_week: dict[int, list] = {}
    for t in task_templates:
        w = int(t["due_week"]) if t.get("due_week") else 0
        templates_by_week.setdefault(w, []).append(t)

    return templates.TemplateResponse(
        "admin_linear.html",
        {
            "request": request,
            "intern_rows": intern_rows,
            "template_count": len(task_templates),
            "weeks": weeks,
            "templates_by_week": templates_by_week,
            "fanout_result": request.query_params.get("result"),
        },
    )


@router.post("/linear/fanout")
async def linear_fanout(
    request: Request,
    session: AdminSession,
    intern_id: str = Form(""),
    week_number: int = Form(0),
):
    """Fan out Task_Templates to Linear issues for one intern or all interns, optionally filtered by week."""
    from app.services.linear import fanout_templates_for_intern  # noqa: PLC0415

    sheets = get_sheets_client()
    all_roster = sheets.get_all_roster()
    tracks = {t.track_id: t for t in sheets.get_all_tracks()}

    ws = sheets._get_worksheet("Task_Templates")
    all_templates = ws.get_all_records()

    if week_number:
        all_templates = [t for t in all_templates if int(t.get("due_week") or 0) == week_number]

    if intern_id:
        targets = [r for r in all_roster if r.intern_id == intern_id and r.role == "intern"]
    else:
        targets = [r for r in all_roster if r.role == "intern" and r.preferred_email]

    total_created = 0
    total_skipped = 0
    errors = []

    for intern in targets:
        track = tracks.get(intern.track_id)
        if not track or not track.linear_project_id:
            errors.append(f"{intern.intern_id}: no Linear project ID for track {intern.track_id}")
            continue

        applicable = [
            t
            for t in all_templates
            if not t.get("assigned_to") or t.get("assigned_to") in ("all", intern.track_id)
        ]

        created = fanout_templates_for_intern(intern, track, applicable)
        skipped = len(applicable) - len(created)
        total_created += len(created)
        total_skipped += skipped
        logger.info(
            "Linear fanout for %s: %d created, %d skipped",
            intern.intern_id,
            len(created),
            skipped,
        )

    week_label = f"Week {week_number}" if week_number else "all weeks"
    result = f"Week {week_number if week_number else 'all'}: created {total_created} issues, skipped {total_skipped} existing"
    if errors:
        result += f" | Errors: {'; '.join(errors)}"
    logger.info("Linear fanout (%s) by %s: %s", week_label, session.email, result)
    return RedirectResponse(url=f"/admin/linear?result={result}", status_code=302)


@router.post("/linear/fix-assignees")
async def linear_fix_assignees(request: Request, session: AdminSession):
    """
    For interns who now have a linear_user_id, patch any existing unassigned issues
    in the SQLite cache to assign them. Run after sync-ids to backfill missing assignees.
    """
    from app.db.sqlite import get_linear_issues_for_intern  # noqa: PLC0415
    from app.services.linear import update_issue_assignee  # noqa: PLC0415

    sheets = get_sheets_client()
    all_roster = sheets.get_all_roster()
    interns = [r for r in all_roster if r.role == "intern" and r.linear_user_id]

    total_fixed = 0
    for intern in interns:
        issues = get_linear_issues_for_intern(intern.intern_id, max_age_seconds=86400)
        for issue in issues:
            if issue.get("state_type") in ("completed", "canceled"):
                continue
            ok = update_issue_assignee(issue["id"], intern.linear_user_id)
            if ok:
                total_fixed += 1

    result = f"Assigned {total_fixed} existing issues to their interns"
    logger.info("Linear fix-assignees by %s: %s", session.email, result)
    return RedirectResponse(url=f"/admin/linear?result={result}", status_code=302)


@router.post("/linear/sync-ids")
async def linear_sync_ids(request: Request, session: AdminSession):
    """
    Look up each intern in Linear by email and save their linear_user_id to the Roster sheet.
    Safe to run repeatedly — only updates rows where linear_user_id is empty.
    """
    from app.services.linear import get_user_by_email  # noqa: PLC0415

    sheets = get_sheets_client()
    all_roster = sheets.get_all_roster()
    interns = [r for r in all_roster if r.role == "intern" and r.preferred_email]

    updated = []
    not_found = []
    for intern in interns:
        if intern.linear_user_id:
            continue  # already linked
        user = get_user_by_email(intern.preferred_email)
        if user:
            sheets.update_roster(intern.intern_id, linear_user_id=user["id"])
            updated.append(intern.display_name)
            logger.info("Linked %s → Linear %s", intern.intern_id, user["id"])
        else:
            not_found.append(intern.display_name)

    invalidate_all()
    parts = []
    if updated:
        parts.append(f"Linked: {', '.join(updated)}")
    if not_found:
        parts.append(f"Not in Linear workspace yet: {', '.join(not_found)}")
    result = " | ".join(parts) or "All interns already linked."
    return RedirectResponse(url=f"/admin/linear?result={result}", status_code=302)
