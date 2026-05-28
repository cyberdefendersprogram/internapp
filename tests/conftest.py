import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up test environment variables."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    # Set environment variables before importing app
    os.environ["SQLITE_PATH"] = temp_path
    os.environ["SECRET_KEY"] = "test-secret-key-for-testing-only-32ch"
    os.environ["BASE_URL"] = "http://localhost:8001"
    os.environ["SMTP_USER"] = "test@example.com"
    os.environ["SMTP_PASS"] = "test-password"
    os.environ["ADMIN_EMAILS"] = "admin@example.com"

    yield temp_path

    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def client(setup_test_env):
    """Create a test client for the FastAPI app."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_sheets():
    """Mock the sheets client."""
    with patch("app.services.sheets.get_sheets_client") as mock:
        sheets = MagicMock()
        mock.return_value = sheets
        yield sheets


@pytest.fixture
def mock_email():
    """Mock the email sending function."""
    with patch("app.services.email.send_magic_link_email") as mock:
        from app.services.email import EmailResult

        mock.return_value = EmailResult(success=True, message_id="test-123")
        yield mock
