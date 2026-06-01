"""Tests for health endpoint."""

from unittest.mock import patch

import pytest

from app.db.sqlite import init_db


@pytest.fixture(autouse=True)
def setup_db(setup_test_env):
    """Initialize database before each test."""
    init_db()


class TestHealth:
    """Tests for /health endpoint."""

    @patch("app.routers.health.get_sheets_client")
    def test_health_returns_200_when_healthy(self, mock_sheets, client):
        """Health endpoint returns 200 when all checks pass."""
        mock_sheets.return_value.check_connection.return_value = True

        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "sqlite" in data["checks"]
        assert "sheets" in data["checks"]
        assert "version" in data
        assert isinstance(data["version"], str)
        assert len(data["version"]) > 0

    @patch("app.routers.health.get_sheets_client")
    def test_health_returns_503_when_sheets_down(self, mock_sheets, client):
        """Health endpoint returns 503 when sheets unavailable."""
        mock_sheets.return_value.check_connection.return_value = False

        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["sheets"] is False

    @patch("app.routers.health.get_sheets_client")
    def test_health_checks_structure(self, mock_sheets, client):
        """Health response has correct structure."""
        mock_sheets.return_value.check_connection.return_value = True

        response = client.get("/health")
        data = response.json()
        assert set(data.keys()) >= {"status", "checks", "version"}
        assert set(data["checks"].keys()) >= {"sqlite", "sheets"}
