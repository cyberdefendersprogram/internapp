"""Public program dashboard route."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import templates
from app.routers.intern import compute_week_number
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/program", response_class=HTMLResponse)
async def program_dashboard(request: Request):
    """
    Public dashboard — no auth required.

    Shows all active tracks, intern names, and deliverables.
    Does NOT expose check-in content, feedback, attendance, ratings, or emails.
    """
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    config = sheets.get_all_config()
    program_title = config.get("program_title", "Cyber Defenders Program")
    program_start = config.get("program_start_date", "")
    total_weeks = config.get("program_weeks", "6")

    tracks = [t for t in sheets.get_all_tracks() if t.is_active]
    all_interns = sheets.get_all_roster()
    all_deliverables = sheets.get_all_deliverables()

    track_data = []
    active_intern_count = 0

    for track in tracks:
        track_interns = [i for i in all_interns if i.track_id == track.track_id]
        active_intern_count += len([i for i in track_interns if i.is_claimed])

        intern_entries = []
        for intern in track_interns:
            intern_deliverables = [
                d for d in all_deliverables if str(d.get("intern_id")) == str(intern.intern_id)
            ]
            intern_entries.append({
                "name": intern.display_name if intern.is_claimed else "TBD",
                "deliverables": [
                    {
                        "title": d.get("title", ""),
                        "url": d.get("url", ""),
                        "week_number": d.get("week_number", ""),
                    }
                    for d in intern_deliverables
                ],
            })

        track_data.append({
            "track": track,
            "interns": intern_entries,
        })

    return templates.TemplateResponse(
        "program.html",
        {
            "request": request,
            "program_title": program_title,
            "program_start": program_start,
            "total_weeks": total_weeks,
            "week_number": week_number,
            "track_count": len(tracks),
            "active_intern_count": active_intern_count,
            "track_data": track_data,
        },
    )
