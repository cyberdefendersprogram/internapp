"""Linear API endpoints — intern-facing issue state updates."""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db.sqlite import get_linear_issues_for_intern, upsert_linear_issue
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
