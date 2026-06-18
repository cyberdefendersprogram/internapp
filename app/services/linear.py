"""Linear GraphQL API client for task management."""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"

# Workflow state IDs for the CDP Interns team (fetched once, stable)
LINEAR_STATES = {
    "Todo": "a46b2991-d1a1-4e2a-b821-0bf92fec0396",
    "In Progress": "5fc4238a-c214-476b-a8a6-2d628f03f015",
    "Done": "f6d027b4-3146-46fc-ae12-e07c8d1f543a",
    "Backlog": "9c841993-44a6-495b-80ce-e701fe06cf72",
    "Canceled": "85338c13-88dd-432c-ac8c-c2b7ffd00792",
}

# Map state name → type (mirrors Linear's classification)
STATE_TYPES = {
    "Todo": "unstarted",
    "In Progress": "started",
    "Done": "completed",
    "Backlog": "backlog",
    "Canceled": "canceled",
    "Duplicate": "duplicate",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": settings.linear_api_key,
        "Content-Type": "application/json",
    }


def _run(query: str, variables: dict | None = None) -> dict[str, Any]:
    """Execute a Linear GraphQL query/mutation. Raises on HTTP or GQL errors."""
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = httpx.post(LINEAR_API_URL, json=payload, headers=_headers(), timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise ValueError(f"Linear GQL error: {data['errors']}")
    return data.get("data", {})


# ── Read ──────────────────────────────────────────────────────────────────────


def get_user_by_email(email: str) -> dict | None:
    """Return Linear user dict {id, name, email} for an email, or None if not a member."""
    q = """
    query UserByEmail($email: String!) {
      users(filter: { email: { eq: $email } }) {
        nodes { id name email }
      }
    }
    """
    try:
        nodes = _run(q, {"email": email.lower()}).get("users", {}).get("nodes", [])
        return nodes[0] if nodes else None
    except Exception as e:
        logger.warning("Linear get_user_by_email(%s) failed: %s", email, e)
        return None


def get_issues_for_project(project_id: str) -> list[dict]:
    """Return all issues in a Linear project with state info."""
    q = """
    query ProjectIssues($projectId: String!) {
      project(id: $projectId) {
        issues(first: 100) {
          nodes {
            id title url
            state { id name type }
            assignee { id email }
            description
            dueDate
          }
        }
      }
    }
    """
    try:
        project = _run(q, {"projectId": project_id}).get("project") or {}
        return project.get("issues", {}).get("nodes", [])
    except Exception as e:
        logger.error("Linear get_issues_for_project(%s) failed: %s", project_id, e)
        return []


def get_issues_for_intern(linear_user_id: str) -> list[dict]:
    """Return open issues assigned to a Linear user."""
    q = """
    query AssigneeIssues($assigneeId: ID!) {
      issues(filter: { assignee: { id: { eq: $assigneeId } } }, first: 50) {
        nodes {
          id title url
          state { id name type }
          description
          project { id name }
        }
      }
    }
    """
    try:
        return _run(q, {"assigneeId": linear_user_id}).get("issues", {}).get("nodes", [])
    except Exception as e:
        logger.error("Linear get_issues_for_intern(%s) failed: %s", linear_user_id, e)
        return []


# ── Write ─────────────────────────────────────────────────────────────────────


def create_issue(
    *,
    title: str,
    description: str,
    project_id: str,
    state_name: str = "Todo",
    assignee_id: str | None = None,
    priority: int = 2,  # 1=urgent 2=high 3=medium 4=low 0=none
) -> dict | None:
    """
    Create a Linear issue. Returns the created issue dict or None on failure.
    Priority mapping: urgent=1, high=2, medium=3, low=4, none=0
    """
    m = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id title url state { name type } }
      }
    }
    """
    inp: dict[str, Any] = {
        "title": title,
        "description": description,
        "teamId": settings.linear_team_id,
        "projectId": project_id,
        "stateId": LINEAR_STATES.get(state_name, LINEAR_STATES["Todo"]),
        "priority": priority,
    }
    if assignee_id:
        inp["assigneeId"] = assignee_id

    try:
        result = _run(m, {"input": inp})
        ic = result.get("issueCreate", {})
        if ic.get("success"):
            return ic["issue"]
        logger.error("Linear issueCreate returned success=false: %s", ic)
        return None
    except Exception as e:
        logger.error("Linear create_issue(%s) failed: %s", title, e)
        return None


def comment_on_issue(issue_id: str, body: str) -> bool:
    """Post a Markdown comment on a Linear issue. Returns True on success."""
    m = """
    mutation AddComment($input: CommentCreateInput!) {
      commentCreate(input: $input) {
        success
        comment { id }
      }
    }
    """
    try:
        result = _run(m, {"input": {"issueId": issue_id, "body": body}})
        return result.get("commentCreate", {}).get("success", False)
    except Exception as e:
        logger.error("Linear comment_on_issue(%s) failed: %s", issue_id, e)
        return False


def update_issue_assignee(issue_id: str, assignee_id: str) -> bool:
    """Set the assignee on an existing Linear issue. Returns True on success."""
    m = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue { id assignee { id name } }
      }
    }
    """
    try:
        result = _run(m, {"id": issue_id, "input": {"assigneeId": assignee_id}})
        return result.get("issueUpdate", {}).get("success", False)
    except Exception as e:
        logger.error("Linear update_issue_assignee(%s) failed: %s", issue_id, e)
        return False


def update_issue_state(issue_id: str, state_name: str) -> bool:
    """Update the workflow state of a Linear issue. Returns True on success."""
    state_id = LINEAR_STATES.get(state_name)
    if not state_id:
        logger.error("Unknown Linear state: %s", state_name)
        return False

    m = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue { id state { name } }
      }
    }
    """
    try:
        result = _run(m, {"id": issue_id, "input": {"stateId": state_id}})
        return result.get("issueUpdate", {}).get("success", False)
    except Exception as e:
        logger.error("Linear update_issue_state(%s → %s) failed: %s", issue_id, state_name, e)
        return False


# ── Fan-out ───────────────────────────────────────────────────────────────────


PRIORITY_MAP = {"urgent": 1, "high": 2, "medium": 3, "normal": 3, "low": 4}


def fanout_templates_for_intern(
    intern,
    track,
    templates: list[dict],
    *,
    dry_run: bool = False,
) -> list[dict]:
    """
    Create Linear issues from Task_Templates for one intern.
    Skips templates already issued (checked via SQLite before calling).
    Returns list of created issue dicts (with intern_id and template_id attached).
    """
    from app.db.sqlite import (  # noqa: PLC0415
        get_linear_issue_by_intern_template,
        upsert_linear_issue,
    )

    created = []
    for tmpl in templates:
        template_id = tmpl.get("template_id", "")
        # Skip if already issued
        if template_id and get_linear_issue_by_intern_template(intern.intern_id, template_id):
            logger.debug("Skipping %s for %s — already exists", template_id, intern.intern_id)
            continue

        title = f"{tmpl['title']} — {intern.display_name}"
        description = _build_description(intern, track, tmpl)
        priority = PRIORITY_MAP.get(str(tmpl.get("priority", "normal")).lower(), 3)

        if dry_run:
            created.append({"dry_run": True, "title": title, "template_id": template_id})
            continue

        issue = create_issue(
            title=title,
            description=description,
            project_id=track.linear_project_id,
            assignee_id=intern.linear_user_id or None,
            priority=priority,
        )
        if not issue:
            logger.error("Failed to create issue %s for %s", template_id, intern.intern_id)
            continue

        state_name = issue.get("state", {}).get("name", "Todo")
        upsert_linear_issue(
            issue_id=issue["id"],
            intern_id=intern.intern_id,
            template_id=template_id,
            title=issue["title"],
            state=state_name,
            state_type=STATE_TYPES.get(state_name, "unstarted"),
            url=issue.get("url", ""),
            due_week=tmpl.get("due_week") or None,
            linked_feature=tmpl.get("linked_feature", ""),
        )
        issue["intern_id"] = intern.intern_id
        issue["template_id"] = template_id
        created.append(issue)
        logger.info(
            "Created Linear issue %s for %s (%s)", issue["id"], intern.intern_id, template_id
        )

    return created


def _build_description(intern, track, tmpl: dict) -> str:
    due = f"Week {tmpl['due_week']}" if tmpl.get("due_week") else "No due date"
    base = tmpl.get("description", "")
    return (
        f"{base}\n\n"
        f"---\n"
        f"**Intern:** {intern.full_name} (`{intern.intern_id}`)\n"
        f"**Track:** {track.name}\n"
        f"**Due:** {due}\n"
        f"**Program portal:** https://intern.cyberdefendersprogram.com/home\n"
    )


def complete_linked_tasks(intern_id: str, week_number: int | None, linked_feature: str) -> int:
    """
    Mark matching Linear issues as Done when an intern completes a feature action
    (e.g. submitting a check-in marks all 'checkin' tasks for that week as Done).
    Returns the number of issues updated.
    """
    from app.db.sqlite import get_linear_issues_for_intern, upsert_linear_issue  # noqa: PLC0415

    issues = get_linear_issues_for_intern(intern_id, max_age_seconds=86400)  # allow stale for this
    completed = 0
    for issue in issues:
        if issue.get("state_type") in ("completed", "canceled"):
            continue
        if issue.get("linked_feature") != linked_feature:
            continue
        if week_number is not None and issue.get("due_week") not in (None, week_number):
            continue

        ok = update_issue_state(issue["id"], "Done")
        if ok:
            upsert_linear_issue(
                issue_id=issue["id"],
                intern_id=intern_id,
                template_id=issue.get("template_id", ""),
                title=issue["title"],
                state="Done",
                state_type="completed",
                url=issue.get("url", ""),
                due_week=issue.get("due_week"),
                linked_feature=linked_feature,
            )
            completed += 1
            logger.info(
                "Marked Linear issue %s Done for %s (%s week %s)",
                issue["id"],
                intern_id,
                linked_feature,
                week_number,
            )
    return completed


def sync_intern_issues_from_linear(intern_id: str, linear_user_id: str) -> list[dict]:
    """
    Pull latest issue states from Linear for an intern and refresh the SQLite cache.
    Called on home page load when cache is stale.
    Returns the refreshed issue list.
    """
    from app.db.sqlite import upsert_linear_issue  # noqa: PLC0415

    issues = get_issues_for_intern(linear_user_id)
    for issue in issues:
        state_name = issue.get("state", {}).get("name", "Todo")
        upsert_linear_issue(
            issue_id=issue["id"],
            intern_id=intern_id,
            template_id="",  # we don't know the template for issues synced from Linear
            title=issue["title"],
            state=state_name,
            state_type=STATE_TYPES.get(state_name, "unstarted"),
            url=issue.get("url", ""),
            due_week=None,
            linked_feature="",
        )
    return issues
