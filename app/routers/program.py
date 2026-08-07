"""Public program dashboard route."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import templates
from app.routers.intern import compute_week_number
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)
router = APIRouter()

FINAL_PRESENTATIONS_DATE = "Tuesday, August 11, 2026"
FINAL_PRESENTATIONS_START = "09:15"  # first presentation slot start (24h)
FINAL_PRESENTATIONS_END = "11:00"  # last presentation slot end (24h)
FINAL_PRESENTATIONS_ZOOM = "https://peralta-edu.zoom.us/j/9402327279"
FINAL_PRESENTATIONS_CALENDAR = (
    "https://www.google.com/calendar/event"
    "?eid=M29paGk4NXEyNjdsOTdlamlvMjg3YmhnZTUgdmFpYmhhdmJAY3liZXJkZWZlbmRlcnNwcm9ncmFtLmNvbQ"
)


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
            if intern.role != "intern" or not intern.is_claimed:
                continue
            intern_deliverables = [
                d for d in all_deliverables if str(d.get("intern_id")) == str(intern.intern_id)
            ]
            intern_entries.append(
                {
                    "name": intern.display_name,
                    "deliverables": [
                        {
                            "title": d.get("title", ""),
                            "url": d.get("url", ""),
                            "week_number": d.get("week_number", ""),
                        }
                        for d in intern_deliverables
                    ],
                }
            )

        track_data.append(
            {
                "track": track,
                "interns": intern_entries,
            }
        )

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


@router.get("/final-presentations", response_class=HTMLResponse)
async def final_presentations(request: Request):
    """
    Public final cohort presentations agenda — no auth required.

    Lists live presentation slots in `presentation_order` (1..N) with computed
    times, plus interns not presenting live (presentation_order == 0, or unset)
    who will still be part of the recorded session at the event.
    """
    sheets = get_sheets_client()
    config = sheets.get_all_config()
    program_title = config.get("program_title", "Cyber Defenders Program")

    tracks = {t.track_id: t for t in sheets.get_all_tracks()}
    all_interns = sheets.get_all_roster()
    presenters = sorted(
        (
            i
            for i in all_interns
            if i.role == "intern" and i.is_claimed and i.presentation_order > 0
        ),
        key=lambda i: i.presentation_order,
    )
    non_presenters = [
        i for i in all_interns if i.role == "intern" and i.is_claimed and i.presentation_order == 0
    ]

    slot_times = _compute_slot_times(
        FINAL_PRESENTATIONS_START, FINAL_PRESENTATIONS_END, len(presenters)
    )

    schedule = []
    for intern, (start, end) in zip(presenters, slot_times, strict=True):
        track = tracks.get(intern.track_id)
        schedule.append(
            {
                "order": intern.presentation_order,
                "start": start,
                "end": end,
                "intern_name": intern.display_name,
                "track_name": track.name if track else "",
                "sponsor": track.employer_sponsor if track else "",
                "project_url": track.project_url if track else "",
            }
        )

    not_presenting = []
    for intern in non_presenters:
        track = tracks.get(intern.track_id)
        not_presenting.append(
            {
                "intern_name": intern.display_name,
                "track_name": track.name if track else "",
                "sponsor": track.employer_sponsor if track else "",
                "project_url": track.project_url if track else "",
            }
        )

    return templates.TemplateResponse(
        "final_presentations.html",
        {
            "request": request,
            "program_title": program_title,
            "event_date": FINAL_PRESENTATIONS_DATE,
            "event_start": FINAL_PRESENTATIONS_START,
            "event_end": FINAL_PRESENTATIONS_END,
            "zoom_url": FINAL_PRESENTATIONS_ZOOM,
            "calendar_url": FINAL_PRESENTATIONS_CALENDAR,
            "schedule": schedule,
            "not_presenting": not_presenting,
        },
    )


def _compute_slot_times(start: str, end: str, count: int) -> list[tuple[str, str]]:
    """Split [start, end) into `count` equal slots, returning ("h:mmam", "h:mmam") tuples."""
    if count <= 0:
        return []
    fmt = "%H:%M"
    start_dt = datetime.strptime(start, fmt)
    end_dt = datetime.strptime(end, fmt)
    slot_len = (end_dt - start_dt) / count

    slots = []
    for i in range(count):
        slot_start = start_dt + slot_len * i
        slot_end = start_dt + slot_len * (i + 1)
        slots.append((_format_time(slot_start), _format_time(slot_end)))
    return slots


def _format_time(dt: datetime) -> str:
    """Format a datetime as e.g. '9:15am' (no leading zero on the hour)."""
    return dt.strftime("%I:%M%p").lstrip("0").lower()
