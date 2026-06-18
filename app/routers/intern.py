"""Intern routes for authenticated interns."""

import logging
import math
from datetime import date, datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db.sqlite import get_cached_intern, get_linear_issues_for_intern, set_cached_intern
from app.dependencies import OnboardedIntern, RequiredSession, templates
from app.services.linear import complete_linked_tasks as linear_complete
from app.services.linear import sync_intern_issues_from_linear
from app.services.sheets import SheetsUnavailableError, get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter()


def compute_week_number(sheets) -> int:
    """Compute current program week number from Config sheet."""
    try:
        start_date_str = sheets.get_config("program_start_date")
        if not start_date_str:
            return 1
        start_date = date.fromisoformat(start_date_str)
        today = date.today()
        if today < start_date:
            return 1
        days_elapsed = (today - start_date).days
        return max(1, math.ceil((days_elapsed + 1) / 7))
    except Exception:
        return 1


_ROLE_REDIRECTS = {
    "admin": "/admin",
    "mentor": "/admin/applicants",
    "sponsor": "/sponsor",
}


@router.get("/home", response_class=HTMLResponse)
async def home(request: Request, session: RequiredSession):
    """Dashboard — redirects admin/mentor/sponsor; renders intern view."""
    if session.role in _ROLE_REDIRECTS:
        return RedirectResponse(url=_ROLE_REDIRECTS[session.role], status_code=302)

    sheets = get_sheets_client()
    intern = get_cached_intern(session.intern_id)
    if not intern:
        try:
            intern = sheets.get_roster_by_id(session.intern_id)
        except SheetsUnavailableError:
            intern = get_cached_intern(session.intern_id, max_age_seconds=86400)
            if not intern:
                raise HTTPException(status_code=503, detail="Service temporarily unavailable.")
        if not intern:
            raise HTTPException(status_code=401, detail="Intern not found")
        set_cached_intern(intern)

    if not intern.onboarding_completed_at:
        return RedirectResponse(url="/onboarding", status_code=302)

    from app.db.sqlite import get_notes_for_intern  # noqa: PLC0415

    track = sheets.get_track_by_id(intern.track_id)
    week_number = compute_week_number(sheets)

    # Find this intern's mentor (roster row with role=mentor on the same track)
    all_roster = sheets.get_all_roster()
    mentor = next(
        (r for r in all_roster if r.role == "mentor" and intern.track_id in r.track_ids),
        None,
    )

    # Check-in status for this week
    checkins = sheets.get_checkins_for_intern(intern.intern_id)
    checked_in_this_week = any(str(c.get("week_number")) == str(week_number) for c in checkins)

    # Tasks from Linear — read local cache; refresh from Linear if intern has a user ID
    linear_tasks = get_linear_issues_for_intern(intern.intern_id)
    if not linear_tasks and intern.linear_user_id:
        sync_intern_issues_from_linear(intern.intern_id, intern.linear_user_id)
        linear_tasks = get_linear_issues_for_intern(intern.intern_id)

    todo_tasks = sorted(
        [t for t in linear_tasks if t["state_type"] not in ("completed", "canceled")],
        key=lambda t: (t.get("due_week") or 99),
    )
    done_tasks = [t for t in linear_tasks if t["state_type"] == "completed"]

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
            "mentor": mentor,
            "meeting_notes": get_notes_for_intern(intern.intern_id, visibility="all"),
            "session": request.cookies.get("session"),
        },
    )


@router.get("/checkin", response_class=HTMLResponse)
async def checkin_form(request: Request, intern: OnboardedIntern):
    """Show check-in form or already-submitted view."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    checkins = sheets.get_checkins_for_intern(intern.intern_id)
    this_week = [c for c in checkins if str(c.get("week_number")) == str(week_number)]
    already_submitted = len(this_week) > 0

    return templates.TemplateResponse(
        "checkin.html",
        {
            "request": request,
            "intern": intern,
            "week_number": week_number,
            "already_submitted": already_submitted,
            "this_week_checkin": this_week[0] if this_week else None,
            "error": None,
            "success": None,
        },
    )


@router.post("/checkin", response_class=HTMLResponse)
async def checkin_submit(
    request: Request,
    intern: OnboardedIntern,
    status_update: str = Form(...),
    blockers: str = Form(""),
    next_steps: str = Form(...),
):
    """Submit weekly check-in."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    # Check if already submitted
    checkins = sheets.get_checkins_for_intern(intern.intern_id)
    already_submitted = any(str(c.get("week_number")) == str(week_number) for c in checkins)

    if already_submitted:
        return templates.TemplateResponse(
            "checkin.html",
            {
                "request": request,
                "intern": intern,
                "week_number": week_number,
                "already_submitted": True,
                "this_week_checkin": None,
                "error": "You have already submitted your check-in for this week.",
                "success": None,
            },
        )

    data = {
        "submitted_at": datetime.utcnow().isoformat(),
        "intern_id": intern.intern_id,
        "email": intern.preferred_email or "",
        "week_number": week_number,
        "status_update": status_update.strip(),
        "blockers": blockers.strip(),
        "next_steps": next_steps.strip(),
    }

    success = sheets.append_checkin(data)

    if success:
        linear_complete(intern.intern_id, week_number, "checkin")

    if not success:
        return templates.TemplateResponse(
            "checkin.html",
            {
                "request": request,
                "intern": intern,
                "week_number": week_number,
                "already_submitted": False,
                "this_week_checkin": None,
                "error": "Failed to submit check-in. Please try again.",
                "success": None,
            },
        )

    logger.info("Check-in submitted: %s week %d", intern.intern_id, week_number)
    return RedirectResponse(url="/checkin?submitted=1", status_code=302)


def _get_deliverable_tasks(intern_id: str) -> tuple[list, list]:
    """Return (open_deliverable_tasks, done_deliverable_tasks) from Linear cache."""
    all_tasks = get_linear_issues_for_intern(intern_id, max_age_seconds=86400)
    open_tasks = [
        t
        for t in all_tasks
        if t.get("linked_feature") == "deliverable"
        and t["state_type"] not in ("completed", "canceled")
    ]
    done_tasks = [
        t
        for t in all_tasks
        if t.get("linked_feature") == "deliverable" and t["state_type"] == "completed"
    ]
    return open_tasks, done_tasks


@router.get("/deliverables", response_class=HTMLResponse)
async def deliverables_page(request: Request, intern: OnboardedIntern):
    """View own deliverables and submit form."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    open_tasks, done_tasks = _get_deliverable_tasks(intern.intern_id)
    submitted = request.query_params.get("submitted") == "1"

    return templates.TemplateResponse(
        "deliverables.html",
        {
            "request": request,
            "intern": intern,
            "open_tasks": open_tasks,
            "done_tasks": done_tasks,
            "week_number": week_number,
            "error": None,
            "success": "Deliverable submitted and Linear task marked Done!" if submitted else None,
        },
    )


@router.post("/deliverables", response_class=HTMLResponse)
async def deliverables_submit(
    request: Request,
    intern: OnboardedIntern,
    url: str = Form(""),
    description: str = Form(""),
    week_number: int = Form(...),
):
    """Mark a Linear deliverable task Done, optionally attaching an artifact URL."""
    from app.db.sqlite import upsert_linear_issue  # noqa: PLC0415
    from app.services.linear import (  # noqa: PLC0415
        STATE_TYPES,
        comment_on_issue,
        update_issue_state,
    )

    open_tasks, done_tasks = _get_deliverable_tasks(intern.intern_id)

    # Find the matching open task for this week (or any open deliverable if week not matched)
    task = next(
        (t for t in open_tasks if t.get("due_week") == week_number),
        open_tasks[0] if open_tasks else None,
    )

    def _render_error(msg: str):
        return templates.TemplateResponse(
            "deliverables.html",
            {
                "request": request,
                "intern": intern,
                "open_tasks": open_tasks,
                "done_tasks": done_tasks,
                "week_number": week_number,
                "error": msg,
                "success": None,
            },
        )

    if not task:
        return _render_error(
            f"No open deliverable task found for Week {week_number}. "
            "Ask your mentor to assign one in Linear."
        )

    url_clean = url.strip()
    description_clean = description.strip()
    if url_clean or description_clean:
        comment_parts = ["**Deliverable submitted**"]
        if url_clean:
            comment_parts.append(f"\n\n**Link:** {url_clean}")
        if description_clean:
            comment_parts.append(f"\n\n{description_clean}")
        comment_on_issue(task["id"], "".join(comment_parts))

    ok = update_issue_state(task["id"], "Done")
    if not ok:
        return _render_error(
            "Could not update Linear task. Please try again or mark it Done in Linear directly."
        )

    upsert_linear_issue(
        issue_id=task["id"],
        intern_id=intern.intern_id,
        template_id=task.get("template_id", ""),
        title=task["title"],
        state="Done",
        state_type=STATE_TYPES["Done"],
        url=task.get("url", ""),
        due_week=task.get("due_week"),
        linked_feature="deliverable",
    )
    logger.info("Deliverable submitted for %s week %d: %s", intern.intern_id, week_number, url)
    return RedirectResponse(url="/deliverables?submitted=1", status_code=302)


@router.get("/me", response_class=HTMLResponse)
async def profile_view(request: Request, intern: OnboardedIntern):
    """Profile view/edit."""
    return templates.TemplateResponse(
        "me.html",
        {
            "request": request,
            "intern": intern,
            "error": None,
            "success": None,
        },
    )


@router.post("/me", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    intern: OnboardedIntern,
    preferred_name: str = Form(""),
    school: str = Form(""),
    year: str = Form(""),
    linkedin: str = Form(""),
    github: str = Form(""),
    bio: str = Form(""),
):
    """Update intern profile."""
    sheets = get_sheets_client()

    fields = {
        "preferred_name": preferred_name.strip(),
        "school": school.strip(),
        "year": year.strip(),
        "linkedin": linkedin.strip(),
        "github": github.strip(),
        "bio": bio.strip(),
    }

    success = sheets.update_roster(intern.intern_id, **fields)

    # Reload updated intern
    updated_intern = sheets.get_roster_by_id(intern.intern_id)

    return templates.TemplateResponse(
        "me.html",
        {
            "request": request,
            "intern": updated_intern or intern,
            "error": None if success else "Failed to update profile.",
            "success": "Profile updated successfully!" if success else None,
        },
    )
