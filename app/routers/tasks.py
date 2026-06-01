"""Tasks API — serves both web and Discord bot."""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException, Path, Query

from app.config import settings
from app.dependencies import AdminOrMentorSession, BotApiKey, RequiredSession
from app.models.task import TaskEntry
from app.services.email import send_discord_link_email
from app.services.sheets import get_sheets_client
from app.services.tokens import create_magic_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _task_to_dict(task: TaskEntry) -> dict:
    return {
        "task_id": task.task_id,
        "title": task.title,
        "task_type": task.task_type,
        "assigned_to": task.assigned_to,
        "assigned_by": task.assigned_by,
        "track_id": task.track_id,
        "week_number": task.week_number,
        "due_week": task.due_week,
        "status": task.status,
        "priority": task.priority,
        "linked_feature": task.linked_feature,
        "source": task.source,
        "description": task.description,
        "skip_reason": task.skip_reason,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


@router.get("")
async def get_tasks(
    session: RequiredSession,
    week: int | None = Query(None),
):
    """Get tasks for the current user, filtered by role."""
    sheets = get_sheets_client()

    if session.role in ("admin",):
        tasks = sheets.get_all_tasks()
    elif session.role == "mentor":
        intern_entry = sheets.get_roster_by_id(session.intern_id)
        track_id = intern_entry.track_id if intern_entry else ""
        tasks = sheets.get_tasks_for_track(track_id) if track_id else []
    else:
        tasks = sheets.get_tasks_for_intern(session.intern_id)

    if week is not None:
        tasks = [t for t in tasks if t.due_week == week or t.week_number == week]

    return {"tasks": [_task_to_dict(t) for t in tasks]}


@router.post("")
async def create_task(
    session: RequiredSession,
    title: str = Body(...),
    description: str = Body(""),
    assigned_to: str = Body(""),
    track_id: str = Body(""),
    week_number: int | None = Body(None),
    due_week: int | None = Body(None),
    priority: str = Body("normal"),
    linked_feature: str = Body(""),
    source: str = Body("web"),
):
    """Create a task. Interns can only create self-tasks."""
    if session.role == "intern":
        task_type = "self"
        assigned_to = session.intern_id
    elif session.role in ("mentor", "admin"):
        task_type = "assigned"
        if not assigned_to:
            assigned_to = session.intern_id
    else:
        raise HTTPException(status_code=403, detail="Not allowed to create tasks")

    task = TaskEntry(
        task_id=str(uuid.uuid4())[:8],
        title=title,
        description=description,
        task_type=task_type,
        assigned_to=assigned_to,
        assigned_by=session.intern_id or "system",
        track_id=track_id,
        week_number=week_number,
        due_week=due_week,
        priority=priority,
        linked_feature=linked_feature,
        source=source,
        status="todo",
        created_at=datetime.utcnow(),
    )

    sheets = get_sheets_client()
    if not sheets.create_task(task):
        raise HTTPException(status_code=500, detail="Failed to create task")

    return {"task": _task_to_dict(task)}


@router.patch("/{task_id}")
async def update_task(
    session: RequiredSession,
    task_id: str = Path(...),
    status: str = Body(...),
    skip_reason: str = Body(""),
):
    """Update a task's status."""
    if status not in ("done", "skipped", "todo"):
        raise HTTPException(status_code=400, detail="Invalid status")
    if status == "skipped" and not skip_reason:
        raise HTTPException(status_code=400, detail="skip_reason required when skipping")

    sheets = get_sheets_client()

    # Verify the task belongs to this user (unless admin/mentor)
    if session.role == "intern":
        intern_tasks = sheets.get_tasks_for_intern(session.intern_id)
        if not any(t.task_id == task_id for t in intern_tasks):
            raise HTTPException(status_code=403, detail="Not your task")

    success = sheets.update_task_status(task_id, status, skip_reason=skip_reason)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task_id": task_id, "status": status}


@router.get("/team")
async def get_team_tasks(
    session: AdminOrMentorSession,
    week: int | None = Query(None),
):
    """Get all tasks for the caller's track (mentor) or all tracks (admin)."""
    sheets = get_sheets_client()

    if session.role == "admin":
        tasks = sheets.get_all_tasks()
    else:
        intern_entry = sheets.get_roster_by_id(session.intern_id)
        track_id = intern_entry.track_id if intern_entry else ""
        tasks = sheets.get_tasks_for_track(track_id) if track_id else []

    if week is not None:
        tasks = [t for t in tasks if t.due_week == week or t.week_number == week]

    return {"tasks": [_task_to_dict(t) for t in tasks]}


@router.get("/overdue")
async def get_overdue_tasks(session: AdminOrMentorSession, current_week: int = Query(...)):
    """Get tasks past their due_week that are still todo."""
    sheets = get_sheets_client()

    if session.role == "admin":
        tasks = sheets.get_all_tasks()
    else:
        intern_entry = sheets.get_roster_by_id(session.intern_id)
        track_id = intern_entry.track_id if intern_entry else ""
        tasks = sheets.get_tasks_for_track(track_id) if track_id else []

    overdue = [
        t
        for t in tasks
        if t.status == "todo" and t.due_week is not None and t.due_week < current_week
    ]
    return {"tasks": [_task_to_dict(t) for t in overdue]}


@router.get("/summary")
async def get_tasks_summary(session: AdminOrMentorSession):
    """Week × track completion matrix."""
    sheets = get_sheets_client()
    tasks = sheets.get_all_tasks()

    summary: dict[str, dict] = {}
    for task in tasks:
        key = f"week{task.due_week or task.week_number or 0}"
        if key not in summary:
            summary[key] = {"total": 0, "done": 0, "skipped": 0, "todo": 0}
        summary[key]["total"] += 1
        summary[key][task.status] = summary[key].get(task.status, 0) + 1

    return {"summary": summary}


# -------------------------------------------------------------------------
# Bot-only endpoints (BOT_API_KEY auth)
# -------------------------------------------------------------------------

bot_router = APIRouter(prefix="/api/bot", tags=["bot"])


@bot_router.get("/tasks")
async def bot_get_tasks(
    _key: BotApiKey,
    discord_id: str = Query(...),
    week: int | None = Query(None),
):
    """Bot: get tasks for a linked Discord user."""
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_discord_id(discord_id)
    if not intern:
        raise HTTPException(status_code=404, detail="Discord user not linked")

    tasks = sheets.get_tasks_for_intern(intern.intern_id)
    if week is not None:
        tasks = [t for t in tasks if t.due_week == week or t.week_number == week]

    return {
        "intern_id": intern.intern_id,
        "display_name": intern.display_name,
        "tasks": [_task_to_dict(t) for t in tasks],
    }


@bot_router.post("/tasks")
async def bot_create_task(
    _key: BotApiKey,
    discord_id: str = Body(...),
    title: str = Body(...),
    description: str = Body(""),
    assigned_to_discord_id: str = Body(""),
    week_number: int | None = Body(None),
    due_week: int | None = Body(None),
    priority: str = Body("normal"),
    source: str = Body("discord"),
):
    """Bot: create a task (self-task or assignment)."""
    sheets = get_sheets_client()
    caller = sheets.get_roster_by_discord_id(discord_id)
    if not caller:
        raise HTTPException(status_code=404, detail="Caller not linked")

    if assigned_to_discord_id and assigned_to_discord_id != discord_id:
        target = sheets.get_roster_by_discord_id(assigned_to_discord_id)
        if not target:
            raise HTTPException(status_code=404, detail="Target user not linked")
        assigned_to = target.intern_id
        task_type = "assigned"
    else:
        assigned_to = caller.intern_id
        task_type = "self"

    task = TaskEntry(
        task_id=str(uuid.uuid4())[:8],
        title=title,
        description=description,
        task_type=task_type,
        assigned_to=assigned_to,
        assigned_by=caller.intern_id,
        week_number=week_number,
        due_week=due_week,
        priority=priority,
        source=source,
        status="todo",
        created_at=datetime.utcnow(),
    )

    if not sheets.create_task(task):
        raise HTTPException(status_code=500, detail="Failed to create task")

    return {"task": _task_to_dict(task)}


@bot_router.post("/discord-link")
async def bot_discord_link(
    _key: BotApiKey,
    email: str = Body(...),
    discord_id: str = Body(...),
):
    """
    Bot: initiate Discord identity linking.

    Looks up the email in the roster, creates a magic token, and sends the user
    an email containing the discord-link URL. The user clicks it to complete
    linking their Discord account to their roster entry.
    """
    email = email.strip().lower()
    sheets = get_sheets_client()

    roster_entry = sheets.get_roster_by_email(email)
    if not roster_entry:
        raise HTTPException(status_code=404, detail="Email not registered in program")

    token = create_magic_token(email)
    link_url = f"{settings.base_url}/auth/discord-link?token={token}&discord_id={discord_id}"

    result = await send_discord_link_email(email, link_url)
    if not result.success:
        logger.error("Failed to send discord-link email to %s: %s", email, result.error)
        raise HTTPException(status_code=500, detail="Failed to send linking email")

    logger.info("Discord link email sent to %s for discord_id %s", email, discord_id)
    return {"sent": True, "email": email}


@bot_router.patch("/tasks/{task_id}")
async def bot_update_task(
    _key: BotApiKey,
    task_id: str = Path(...),
    discord_id: str = Body(...),
    status: str = Body(...),
    skip_reason: str = Body(""),
):
    """Bot: update task status."""
    if status not in ("done", "skipped", "todo"):
        raise HTTPException(status_code=400, detail="Invalid status")

    sheets = get_sheets_client()
    intern = sheets.get_roster_by_discord_id(discord_id)
    if not intern:
        raise HTTPException(status_code=404, detail="Discord user not linked")

    success = sheets.update_task_status(task_id, status, skip_reason=skip_reason)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"task_id": task_id, "status": status}
