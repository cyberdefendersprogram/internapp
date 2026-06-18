"""Linear API endpoints — intern-facing issue state updates and webhook receiver."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.sqlite import (
    get_linear_issue_by_id,
    get_linear_issues_for_intern,
    upsert_linear_issue,
)
from app.dependencies import OnboardedIntern
from app.services.linear import STATE_TYPES, update_issue_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/linear", tags=["linear"])


@router.post("/issues/{issue_id}/done")
async def mark_issue_done(issue_id: str, intern: OnboardedIntern):
    """Mark a Linear issue as Done. Only the issue's assigned intern can do this."""
    # Verify the issue belongs to this intern
    issues = get_linear_issues_for_intern(intern.intern_id, max_age_seconds=86400)
    issue = next((i for i in issues if i["id"] == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found for this intern")

    if issue.get("state_type") == "completed":
        return JSONResponse({"ok": True, "state": "Done"})

    ok = update_issue_state(issue_id, "Done")
    if not ok:
        raise HTTPException(status_code=502, detail="Linear update failed")

    upsert_linear_issue(
        issue_id=issue_id,
        intern_id=intern.intern_id,
        template_id=issue.get("template_id", ""),
        title=issue["title"],
        state="Done",
        state_type=STATE_TYPES["Done"],
        url=issue.get("url", ""),
        due_week=issue.get("due_week"),
        linked_feature=issue.get("linked_feature", ""),
    )
    logger.info("Intern %s marked issue %s Done", intern.intern_id, issue_id)
    return JSONResponse({"ok": True, "state": "Done"})


# ── Webhook receiver ───────────────────────────────────────────────────────────

# Messages sent to interns for each event
_DM_TEMPLATES = {
    "assigned": ("📋 You've been assigned a new task in Linear:\n**{title}**\n{url}"),
    "completed_by_other": ("✅ Your Linear task was marked done:\n**{title}**\n{url}"),
    "comment": ("💬 New comment on your Linear task:\n**{title}**\n{url}"),
}


def _verify_linear_signature(body: bytes, signature: str) -> bool:
    """Verify Linear's HMAC-SHA256 webhook signature."""
    secret = settings.linear_webhook_secret
    if not secret:
        logger.warning("LINEAR_WEBHOOK_SECRET not set — skipping signature check")
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def linear_webhook(request: Request):
    """
    Receive Linear webhook events and DM the relevant intern on Discord.

    Events handled:
    - Issue assigned → DM the assignee
    - Issue moved to Done (by someone other than the intern) → DM the assignee
    - Comment created on an intern's issue → DM the assignee
    """
    body = await request.body()
    sig = request.headers.get("Linear-Signature", "")

    if not _verify_linear_signature(body, sig):
        logger.warning("Linear webhook signature mismatch")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    action = payload.get("action")  # "create" | "update" | "remove"
    event_type = payload.get("type")  # "Issue" | "Comment" | ...
    data = payload.get("data", {})

    logger.debug("Linear webhook: type=%s action=%s id=%s", event_type, action, data.get("id"))

    if event_type == "Issue":
        await _handle_issue_event(action, data)
    elif event_type == "Comment":
        await _handle_comment_event(data)

    return JSONResponse({"ok": True})


async def _handle_issue_event(action: str, data: dict) -> None:
    from app.services.discord import send_dm  # noqa: PLC0415
    from app.services.sheets import get_sheets_client  # noqa: PLC0415

    issue_id = data.get("id", "")
    title = data.get("title", "")
    url = data.get("url", "")
    state_type = data.get("state", {}).get("type", "")
    assignee = data.get("assignee") or {}
    assignee_linear_id = assignee.get("id")

    # Resolve intern from our SQLite cache
    cached = get_linear_issue_by_id(issue_id)
    intern_id = cached["intern_id"] if cached else None

    # If not in cache, try to match via assignee Linear user ID
    if not intern_id and assignee_linear_id:
        sheets = get_sheets_client()
        roster = sheets.get_all_roster()
        match = next((r for r in roster if r.linear_user_id == assignee_linear_id), None)
        intern_id = match.intern_id if match else None

    if not intern_id:
        return

    # Get intern's discord_id
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_id(intern_id)
    if not intern or not intern.discord_id:
        return

    # Decide which DM to send
    if action == "update" and state_type == "completed":
        # Only DM if completed by someone else (the intern completing via portal is self-initiated)
        if not cached or cached.get("state_type") == "completed":
            return  # already knew it was done
        msg = _DM_TEMPLATES["completed_by_other"].format(title=title, url=url)
        send_dm(intern.discord_id, msg)
        # Refresh cache
        upsert_linear_issue(
            issue_id=issue_id,
            intern_id=intern_id,
            template_id=cached.get("template_id", "") if cached else "",
            title=title,
            state="Done",
            state_type="completed",
            url=url,
            due_week=cached.get("due_week") if cached else None,
            linked_feature=cached.get("linked_feature", "") if cached else "",
        )
    elif action == "update" and assignee_linear_id:
        # Issue was (re)assigned — check if assignee changed
        msg = _DM_TEMPLATES["assigned"].format(title=title, url=url)
        send_dm(intern.discord_id, msg)
    elif action == "create" and assignee_linear_id:
        msg = _DM_TEMPLATES["assigned"].format(title=title, url=url)
        send_dm(intern.discord_id, msg)


async def _handle_comment_event(data: dict) -> None:
    from app.services.discord import send_dm  # noqa: PLC0415
    from app.services.sheets import get_sheets_client  # noqa: PLC0415

    issue_id = data.get("issue", {}).get("id", "")
    issue_title = data.get("issue", {}).get("title", "")
    issue_url = data.get("issue", {}).get("url", "")
    author_id = data.get("user", {}).get("id", "")

    if not issue_id:
        return

    cached = get_linear_issue_by_id(issue_id)
    if not cached:
        return

    # Don't DM the intern about their own comments
    sheets = get_sheets_client()
    intern = sheets.get_roster_by_id(cached["intern_id"])
    if not intern or not intern.discord_id:
        return
    if intern.linear_user_id and author_id == intern.linear_user_id:
        return

    msg = _DM_TEMPLATES["comment"].format(title=issue_title, url=issue_url)
    send_dm(intern.discord_id, msg)
