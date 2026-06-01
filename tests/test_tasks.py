"""Tests for tasks API endpoints and TaskEntry model."""

from datetime import datetime
from unittest.mock import patch

import pytest

from app.db.sqlite import init_db
from app.models.task import TaskEntry
from app.services.sessions import create_session_token


@pytest.fixture(autouse=True)
def setup_db(setup_test_env):
    init_db()


def _session(role: str, intern_id: str = "CDP-2026-001") -> str:
    return create_session_token(f"{role}@example.com", intern_id, role)


# ---------------------------------------------------------------------------
# TaskEntry model
# ---------------------------------------------------------------------------


class TestTaskEntry:
    def test_from_row_basic(self):
        row = {
            "task_id": "abc123",
            "title": "Do a thing",
            "task_type": "system",
            "assigned_to": "CDP-2026-001",
            "assigned_by": "system",
            "status": "todo",
            "priority": "normal",
            "week_number": 1,
            "due_week": 1,
            "linked_feature": "checkin",
            "created_at": "2026-06-01T09:00:00",
        }
        task = TaskEntry.from_row(row)
        assert task.task_id == "abc123"
        assert task.title == "Do a thing"
        assert task.status == "todo"
        assert task.week_number == 1
        assert task.linked_feature == "checkin"
        assert task.created_at is not None

    def test_from_row_empty_week_is_none(self):
        task = TaskEntry.from_row({"task_id": "x", "title": "T", "week_number": "", "due_week": ""})
        assert task.week_number is None
        assert task.due_week is None

    def test_to_row_roundtrip(self):
        headers = [
            "task_id",
            "title",
            "description",
            "task_type",
            "assigned_to",
            "assigned_by",
            "track_id",
            "week_number",
            "due_week",
            "status",
            "priority",
            "linked_feature",
            "source",
            "skip_reason",
            "created_at",
            "completed_at",
        ]
        task = TaskEntry(
            task_id="t1",
            title="My task",
            task_type="self",
            assigned_to="CDP-001",
            status="todo",
            priority="high",
            week_number=2,
            due_week=2,
            created_at=datetime(2026, 6, 1),
        )
        row = task.to_row(headers)
        assert row[headers.index("task_id")] == "t1"
        assert row[headers.index("title")] == "My task"
        assert row[headers.index("priority")] == "high"
        assert row[headers.index("week_number")] == 2

    def test_defaults(self):
        task = TaskEntry(task_id="x", title="T")
        assert task.status == "todo"
        assert task.priority == "normal"
        assert task.task_type == "system"
        assert task.source == "system"
        assert task.skip_reason == ""


# ---------------------------------------------------------------------------
# GET /api/tasks — intern sees own tasks
# ---------------------------------------------------------------------------


class TestGetTasks:
    @patch("app.routers.tasks.get_sheets_client")
    def test_intern_gets_own_tasks(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = [
            TaskEntry(
                task_id="t1",
                title="Submit check-in",
                assigned_to="CDP-2026-001",
                status="todo",
                priority="normal",
                week_number=1,
                due_week=1,
            )
        ]
        token = _session("intern", "CDP-2026-001")
        resp = client.get("/api/tasks", cookies={"session": token})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["task_id"] == "t1"

    @patch("app.routers.tasks.get_sheets_client")
    def test_intern_can_filter_by_week(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = [
            TaskEntry(task_id="w1", title="Week 1 task", due_week=1),
            TaskEntry(task_id="w2", title="Week 2 task", due_week=2),
        ]
        token = _session("intern")
        resp = client.get("/api/tasks?week=1", cookies={"session": token})
        assert resp.status_code == 200
        ids = [t["task_id"] for t in resp.json()["tasks"]]
        assert "w1" in ids
        assert "w2" not in ids

    def test_unauthenticated_returns_401(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 401

    @patch("app.routers.tasks.get_sheets_client")
    def test_admin_gets_all_tasks(self, mock_sheets, client):
        mock_sheets.return_value.get_all_tasks.return_value = [
            TaskEntry(task_id="a1", title="All interns task"),
        ]
        token = _session("admin", "")
        resp = client.get("/api/tasks", cookies={"session": token})
        assert resp.status_code == 200
        mock_sheets.return_value.get_all_tasks.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/tasks — create task
# ---------------------------------------------------------------------------


class TestCreateTask:
    @patch("app.routers.tasks.get_sheets_client")
    def test_intern_creates_self_task(self, mock_sheets, client):
        mock_sheets.return_value.create_task.return_value = True
        token = _session("intern", "CDP-2026-001")
        resp = client.post(
            "/api/tasks",
            json={"title": "Read MITRE ATT&CK"},
            cookies={"session": token},
        )
        assert resp.status_code == 200
        task = resp.json()["task"]
        assert task["task_type"] == "self"
        assert task["assigned_to"] == "CDP-2026-001"
        assert task["status"] == "todo"

    @patch("app.routers.tasks.get_sheets_client")
    def test_mentor_creates_assigned_task(self, mock_sheets, client):
        mock_sheets.return_value.create_task.return_value = True
        token = _session("mentor", "CDP-2026-M01")
        resp = client.post(
            "/api/tasks",
            json={"title": "Review CVE", "assigned_to": "CDP-2026-001", "priority": "high"},
            cookies={"session": token},
        )
        assert resp.status_code == 200
        task = resp.json()["task"]
        assert task["task_type"] == "assigned"
        assert task["priority"] == "high"

    @patch("app.routers.tasks.get_sheets_client")
    def test_create_task_sheets_failure_returns_500(self, mock_sheets, client):
        mock_sheets.return_value.create_task.return_value = False
        token = _session("intern")
        resp = client.post(
            "/api/tasks",
            json={"title": "Failing task"},
            cookies={"session": token},
        )
        assert resp.status_code == 500

    def test_sponsor_cannot_create_task(self, client):
        token = _session("sponsor", "")
        resp = client.post(
            "/api/tasks",
            json={"title": "Sponsor task"},
            cookies={"session": token},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/tasks/{task_id}
# ---------------------------------------------------------------------------


class TestUpdateTask:
    @patch("app.routers.tasks.get_sheets_client")
    def test_intern_marks_task_done(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = [
            TaskEntry(task_id="t99", title="Task", assigned_to="CDP-2026-001")
        ]
        mock_sheets.return_value.update_task_status.return_value = True
        token = _session("intern", "CDP-2026-001")
        resp = client.patch(
            "/api/tasks/t99",
            json={"status": "done"},
            cookies={"session": token},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    @patch("app.routers.tasks.get_sheets_client")
    def test_skip_requires_reason(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = [
            TaskEntry(task_id="t1", title="Task")
        ]
        token = _session("intern")
        resp = client.patch(
            "/api/tasks/t1",
            json={"status": "skipped", "skip_reason": ""},
            cookies={"session": token},
        )
        assert resp.status_code == 400

    @patch("app.routers.tasks.get_sheets_client")
    def test_invalid_status_rejected(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = []
        token = _session("intern")
        resp = client.patch(
            "/api/tasks/t1",
            json={"status": "cancelled"},
            cookies={"session": token},
        )
        assert resp.status_code == 400

    @patch("app.routers.tasks.get_sheets_client")
    def test_intern_cannot_update_others_task(self, mock_sheets, client):
        mock_sheets.return_value.get_tasks_for_intern.return_value = []  # no tasks for this intern
        mock_sheets.return_value.update_task_status.return_value = True
        token = _session("intern", "CDP-2026-002")
        resp = client.patch(
            "/api/tasks/someone-elses-task",
            json={"status": "done"},
            cookies={"session": token},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/tasks/team and /api/tasks/summary
# ---------------------------------------------------------------------------


class TestTeamTasks:
    @patch("app.routers.tasks.get_sheets_client")
    def test_mentor_gets_track_tasks(self, mock_sheets, client):
        from app.models.intern import InternEntry

        mock_sheets.return_value.get_roster_by_id.return_value = InternEntry(
            intern_id="CDP-2026-M01", full_name="Mentor", track_id="track-1"
        )
        mock_sheets.return_value.get_tasks_for_track.return_value = [
            TaskEntry(task_id="tt1", title="Track task", track_id="track-1")
        ]
        token = _session("mentor", "CDP-2026-M01")
        resp = client.get("/api/tasks/team", cookies={"session": token})
        assert resp.status_code == 200
        assert len(resp.json()["tasks"]) == 1

    def test_intern_cannot_access_team_tasks(self, client):
        token = _session("intern")
        resp = client.get("/api/tasks/team", cookies={"session": token})
        assert resp.status_code == 403

    @patch("app.routers.tasks.get_sheets_client")
    def test_admin_gets_summary(self, mock_sheets, client):
        mock_sheets.return_value.get_all_tasks.return_value = [
            TaskEntry(task_id="s1", title="T1", status="done", due_week=1),
            TaskEntry(task_id="s2", title="T2", status="todo", due_week=1),
            TaskEntry(task_id="s3", title="T3", status="todo", due_week=2),
        ]
        token = _session("admin", "")
        resp = client.get("/api/tasks/summary", cookies={"session": token})
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["week1"]["done"] == 1
        assert summary["week1"]["todo"] == 1
        assert summary["week2"]["todo"] == 1


# ---------------------------------------------------------------------------
# GET /api/tasks/overdue
# ---------------------------------------------------------------------------


class TestOverdueTasks:
    @patch("app.routers.tasks.get_sheets_client")
    def test_returns_only_overdue_todo_tasks(self, mock_sheets, client):
        mock_sheets.return_value.get_all_tasks.return_value = [
            TaskEntry(task_id="o1", title="Overdue", status="todo", due_week=1),
            TaskEntry(task_id="o2", title="On time", status="todo", due_week=3),
            TaskEntry(task_id="o3", title="Done overdue", status="done", due_week=1),
        ]
        token = _session("admin", "")
        resp = client.get("/api/tasks/overdue?current_week=2", cookies={"session": token})
        assert resp.status_code == 200
        ids = [t["task_id"] for t in resp.json()["tasks"]]
        assert "o1" in ids
        assert "o2" not in ids  # not yet due
        assert "o3" not in ids  # already done


# ---------------------------------------------------------------------------
# Discord identity linking — GET /auth/discord-link
# ---------------------------------------------------------------------------


class TestDiscordLink:
    @patch("app.routers.auth.get_sheets_client")
    def test_invalid_token_shows_error(self, mock_sheets, client):
        resp = client.get("/auth/discord-link?token=bad-token&discord_id=123456")
        assert resp.status_code == 200
        assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()

    @patch("app.routers.auth.get_sheets_client")
    def test_unregistered_email_shows_error(self, mock_sheets, client):
        from app.services.tokens import create_magic_token

        token = create_magic_token("nobody@example.com")
        mock_sheets.return_value.get_roster_by_email.return_value = None
        resp = client.get(f"/auth/discord-link?token={token}&discord_id=999")
        assert resp.status_code == 200
        assert "not registered" in resp.text.lower()

    @patch("app.routers.auth.get_sheets_client")
    def test_successful_link_shows_success(self, mock_sheets, client):
        from datetime import datetime

        from app.models.intern import InternEntry
        from app.services.tokens import create_magic_token

        token = create_magic_token("intern@example.com")
        mock_sheets.return_value.get_roster_by_email.return_value = InternEntry(
            intern_id="CDP-2026-001",
            full_name="Doe, Jane",
            preferred_email="intern@example.com",
            claimed_at=datetime(2026, 6, 1),
        )
        mock_sheets.return_value.link_discord_id.return_value = True

        resp = client.get(f"/auth/discord-link?token={token}&discord_id=987654321")
        assert resp.status_code == 200
        assert "linked" in resp.text.lower()
        mock_sheets.return_value.link_discord_id.assert_called_once_with(
            "CDP-2026-001", "987654321"
        )

    @patch("app.routers.auth.get_sheets_client")
    def test_sheets_failure_shows_error(self, mock_sheets, client):
        from datetime import datetime

        from app.models.intern import InternEntry
        from app.services.tokens import create_magic_token

        token = create_magic_token("intern@example.com")
        mock_sheets.return_value.get_roster_by_email.return_value = InternEntry(
            intern_id="CDP-2026-001",
            full_name="Doe, Jane",
            preferred_email="intern@example.com",
            claimed_at=datetime(2026, 6, 1),
        )
        mock_sheets.return_value.link_discord_id.return_value = False

        resp = client.get(f"/auth/discord-link?token={token}&discord_id=987654321")
        assert resp.status_code == 200
        assert "failed" in resp.text.lower() or "try again" in resp.text.lower()


# ---------------------------------------------------------------------------
# Bot endpoints — /api/bot/tasks
# ---------------------------------------------------------------------------


class TestBotEndpoints:
    BOT_TOKEN = "test-bot-token-abc"

    @pytest.fixture(autouse=True)
    def set_bot_token(self):
        from app.config import settings

        with patch.object(settings, "discord_cdpbot_token", self.BOT_TOKEN):
            yield

    @patch("app.routers.tasks.get_sheets_client")
    def test_bot_get_tasks_for_linked_user(self, mock_sheets, client):
        from app.models.intern import InternEntry

        mock_sheets.return_value.get_roster_by_discord_id.return_value = InternEntry(
            intern_id="CDP-2026-001",
            full_name="Doe, Jane",
            preferred_name="Jane",
            preferred_email="jane@example.com",
        )
        mock_sheets.return_value.get_tasks_for_intern.return_value = [
            TaskEntry(task_id="b1", title="Bot task", status="todo")
        ]
        resp = client.get(
            "/api/bot/tasks?discord_id=111222333",
            headers={"x-api-key": self.BOT_TOKEN},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intern_id"] == "CDP-2026-001"
        assert len(data["tasks"]) == 1

    @patch("app.routers.tasks.get_sheets_client")
    def test_bot_unlinked_user_returns_404(self, mock_sheets, client):
        mock_sheets.return_value.get_roster_by_discord_id.return_value = None
        resp = client.get(
            "/api/bot/tasks?discord_id=000000",
            headers={"x-api-key": self.BOT_TOKEN},
        )
        assert resp.status_code == 404

    def test_bot_missing_api_key_returns_401(self, client):
        resp = client.get("/api/bot/tasks?discord_id=123")
        assert resp.status_code in (401, 503)

    def test_bot_wrong_api_key_returns_401(self, client):
        resp = client.get(
            "/api/bot/tasks?discord_id=123",
            headers={"x-api-key": "wrong-key"},
        )
        assert resp.status_code == 401

    @patch("app.routers.tasks.get_sheets_client")
    def test_bot_create_self_task(self, mock_sheets, client):
        from app.models.intern import InternEntry

        caller = InternEntry(intern_id="CDP-2026-001", full_name="Doe, Jane")
        mock_sheets.return_value.get_roster_by_discord_id.return_value = caller
        mock_sheets.return_value.create_task.return_value = True

        resp = client.post(
            "/api/bot/tasks",
            json={"discord_id": "111", "title": "My Discord task"},
            headers={"x-api-key": self.BOT_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["task"]["task_type"] == "self"

    @patch("app.routers.tasks.get_sheets_client")
    def test_bot_update_task_status(self, mock_sheets, client):
        from app.models.intern import InternEntry

        mock_sheets.return_value.get_roster_by_discord_id.return_value = InternEntry(
            intern_id="CDP-2026-001", full_name="Doe, Jane"
        )
        mock_sheets.return_value.update_task_status.return_value = True

        resp = client.patch(
            "/api/bot/tasks/t1",
            json={"discord_id": "111", "status": "done"},
            headers={"x-api-key": self.BOT_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"
