"""Sponsor routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import SponsorSession, templates
from app.routers.intern import compute_week_number
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sponsor")


@router.get("", response_class=HTMLResponse)
async def sponsor_home(request: Request, session: SponsorSession):
    """Show sponsor's track interns with check-in status."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    # Get sponsor's track
    track = sheets.get_track_by_sponsor_email(session.email)
    if not track and session.role == "admin":
        # Admins can view sponsor view for any track; use all tracks
        tracks = sheets.get_all_tracks()
        all_interns = sheets.get_all_roster()
        # Build data for all tracks
        track_data = []
        for t in tracks:
            interns = [i for i in all_interns if i.track_id == t.track_id]
            intern_rows = []
            for intern in interns:
                checkins = sheets.get_checkins_for_intern(intern.intern_id)
                checked_in = any(str(c.get("week_number")) == str(week_number) for c in checkins)
                intern_rows.append({"intern": intern, "checked_in": checked_in})
            track_data.append({"track": t, "interns": intern_rows})
        return templates.TemplateResponse(
            "sponsor.html",
            {
                "request": request,
                "track": None,
                "track_data": track_data,
                "week_number": week_number,
                "is_admin_view": True,
            },
        )

    if not track:
        return HTMLResponse("Track not found for your email.", status_code=404)

    all_interns = sheets.get_all_roster()
    track_interns = [i for i in all_interns if i.track_id == track.track_id]

    intern_rows = []
    for intern in track_interns:
        checkins = sheets.get_checkins_for_intern(intern.intern_id)
        checked_in = any(str(c.get("week_number")) == str(week_number) for c in checkins)
        deliverable_count = len(sheets.get_deliverables_for_intern(intern.intern_id))
        intern_rows.append({
            "intern": intern,
            "checked_in": checked_in,
            "deliverable_count": deliverable_count,
        })

    return templates.TemplateResponse(
        "sponsor.html",
        {
            "request": request,
            "track": track,
            "track_data": None,
            "intern_rows": intern_rows,
            "week_number": week_number,
            "is_admin_view": False,
        },
    )


@router.get("/intern/{intern_id}", response_class=HTMLResponse)
async def sponsor_intern_detail(request: Request, intern_id: str, session: SponsorSession):
    """Intern detail view for sponsor."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    intern = sheets.get_roster_by_id(intern_id)
    if not intern:
        return HTMLResponse("Intern not found.", status_code=404)

    # Verify sponsor has access to this intern's track
    if session.role == "sponsor":
        track = sheets.get_track_by_sponsor_email(session.email)
        if not track or track.track_id != intern.track_id:
            return HTMLResponse("Access denied.", status_code=403)

    track = sheets.get_track_by_id(intern.track_id)
    checkins = sheets.get_checkins_for_intern(intern_id)
    deliverables = sheets.get_deliverables_for_intern(intern_id)
    feedback_list = sheets.get_feedback_for_intern(intern_id)

    return templates.TemplateResponse(
        "sponsor_intern.html",
        {
            "request": request,
            "intern": intern,
            "track": track,
            "checkins": sorted(checkins, key=lambda c: c.get("submitted_at", ""), reverse=True),
            "deliverables": sorted(deliverables, key=lambda d: d.get("submitted_at", ""), reverse=True),
            "feedback_list": feedback_list,
            "week_number": week_number,
            "error": None,
            "success": None,
        },
    )


@router.get("/feedback", response_class=HTMLResponse)
async def feedback_form(request: Request, session: SponsorSession):
    """Feedback form for sponsor."""
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)

    track = sheets.get_track_by_sponsor_email(session.email)
    all_interns = sheets.get_all_roster()
    if track:
        interns = [i for i in all_interns if i.track_id == track.track_id and i.is_claimed]
    else:
        interns = [i for i in all_interns if i.is_claimed]

    return templates.TemplateResponse(
        "sponsor_intern.html",
        {
            "request": request,
            "intern": None,
            "track": track,
            "interns": interns,
            "week_number": week_number,
            "checkins": [],
            "deliverables": [],
            "feedback_list": [],
            "error": None,
            "success": None,
            "feedback_only": True,
        },
    )


@router.post("/feedback", response_class=HTMLResponse)
async def feedback_submit(
    request: Request,
    session: SponsorSession,
    intern_id: str = Form(...),
    week_number: int = Form(...),
    rating: int = Form(...),
    feedback: str = Form(...),
):
    """Submit mentor feedback."""
    sheets = get_sheets_client()

    data = {
        "submitted_at": datetime.utcnow().isoformat(),
        "intern_id": intern_id,
        "week_number": week_number,
        "reviewer_email": session.email,
        "rating": rating,
        "feedback": feedback.strip(),
    }

    success = sheets.append_feedback(data)

    logger.info("Feedback submitted by %s for intern %s", session.email, intern_id)

    # Redirect back to intern detail
    return RedirectResponse(
        url=f"/sponsor/intern/{intern_id}?feedback_submitted=1",
        status_code=302,
    )
