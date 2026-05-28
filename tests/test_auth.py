"""Tests for authentication routes."""

import uuid
from unittest.mock import patch

import pytest

from app.db.sqlite import init_db
from app.services.email import EmailResult


@pytest.fixture(autouse=True)
def setup_db(setup_test_env):
    """Initialize database before each test."""
    init_db()


class TestSigninPage:
    """Tests for sign-in page."""

    def test_signin_page_renders(self, client):
        """Sign-in page renders successfully."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Cyber Defenders" in response.text or "Sign In" in response.text

    def test_signin_redirects_admin_if_logged_in(self, client):
        """Logged-in admin is redirected to /admin."""
        from app.services.sessions import create_session_token

        token = create_session_token("admin@example.com", "", "admin")
        response = client.get("/", cookies={"session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/admin" in response.headers["location"]

    def test_signin_redirects_sponsor_if_logged_in(self, client):
        """Logged-in sponsor is redirected to /sponsor."""
        from app.services.sessions import create_session_token

        token = create_session_token("sponsor@example.com", "", "sponsor")
        response = client.get("/", cookies={"session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/sponsor" in response.headers["location"]

    def test_signin_redirects_intern_if_logged_in(self, client):
        """Logged-in intern is redirected to /home."""
        from app.services.sessions import create_session_token

        token = create_session_token("intern@example.com", "CDP-2026-001", "intern")
        response = client.get("/", cookies={"session": token}, follow_redirects=False)
        assert response.status_code == 302
        assert "/home" in response.headers["location"]


class TestRequestMagicLink:
    """Tests for magic link request endpoint."""

    @patch("app.routers.auth.send_magic_link_email")
    @patch("app.routers.auth.get_sheets_client")
    def test_request_link_success(self, mock_sheets, mock_email, client):
        """Magic link request shows success message."""
        mock_sheets.return_value.append_magic_link_request.return_value = True
        mock_email.return_value = EmailResult(success=True, message_id="123")

        email = f"test-{uuid.uuid4()}@example.com"
        response = client.post("/auth/request-link", data={"email": email})

        assert response.status_code == 200
        assert "check your inbox" in response.text.lower()
        mock_email.assert_called_once()

    @patch("app.routers.auth.get_sheets_client")
    def test_request_link_rate_limited(self, mock_sheets, client):
        """Rate limiting returns error after too many requests (limit is 10)."""
        mock_sheets.return_value.append_magic_link_request.return_value = True

        email = f"ratelimited-{uuid.uuid4()}@example.com"

        # Exhaust the 10-request limit
        with patch("app.routers.auth.send_magic_link_email") as mock_email:
            mock_email.return_value = EmailResult(success=True)
            for _ in range(10):
                client.post("/auth/request-link", data={"email": email})

        # 11th request should be rate limited
        response = client.post("/auth/request-link", data={"email": email})
        assert response.status_code == 200
        assert "too many requests" in response.text.lower()

    @patch("app.routers.auth.send_magic_link_email")
    @patch("app.routers.auth.get_sheets_client")
    def test_request_link_unknown_email_shows_success(self, mock_sheets, mock_email, client):
        """Unknown emails get same success response (no enumeration)."""
        mock_sheets.return_value.append_magic_link_request.return_value = True
        mock_email.return_value = EmailResult(success=True)

        email = f"unknown-{uuid.uuid4()}@nonexistent.com"
        response = client.post("/auth/request-link", data={"email": email})

        assert response.status_code == 200
        assert "check your inbox" in response.text.lower()


class TestVerifyMagicLink:
    """Tests for magic link verification."""

    def test_invalid_token_shows_error(self, client):
        """Invalid token shows error message."""
        response = client.get("/auth/verify?token=invalid-token-xyz")
        assert response.status_code == 200
        assert "invalid" in response.text.lower() or "expired" in response.text.lower()

    @patch("app.routers.auth.get_sheets_client")
    @patch("app.routers.auth.settings")
    def test_admin_email_redirects_to_admin(self, mock_settings, mock_sheets, client):
        """Admin email redirects to /admin."""
        from app.services.tokens import create_magic_token

        token = create_magic_token("admin@example.com")
        # Patch settings so admin_email_list returns the test admin email
        mock_settings.admin_email_list = ["admin@example.com"]
        mock_settings.base_url = "http://localhost:8001"
        mock_settings.magic_link_ttl_minutes = 15
        mock_settings.secret_key = "test-secret-key-for-testing-only-32ch"
        mock_settings.is_development = True

        mock_sheets.return_value.get_track_by_sponsor_email.return_value = None
        mock_sheets.return_value.get_roster_by_email.return_value = None

        response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
        assert response.status_code == 302
        assert "/admin" in response.headers["location"]
        assert "session" in response.cookies

    @patch("app.routers.auth.get_sheets_client")
    def test_sponsor_email_redirects_to_sponsor(self, mock_sheets, client):
        """Sponsor email redirects to /sponsor."""
        from app.models.track import TrackEntry
        from app.services.tokens import create_magic_token

        token = create_magic_token("sponsor@track1.com")

        mock_track = TrackEntry(
            track_id="track-1",
            name="Test Track",
            sponsor_email="sponsor@track1.com",
        )
        mock_sheets.return_value.get_roster_by_email.return_value = None
        mock_sheets.return_value.get_track_by_sponsor_email.return_value = mock_track

        response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
        assert response.status_code == 302
        assert "/sponsor" in response.headers["location"]
        assert "session" in response.cookies

    @patch("app.routers.auth.get_sheets_client")
    def test_claimed_intern_redirects_to_home(self, mock_sheets, client):
        """Valid token for claimed intern redirects to /home."""
        from datetime import datetime

        from app.models.intern import InternEntry
        from app.services.tokens import create_magic_token

        token = create_magic_token("intern@example.com")

        mock_entry = InternEntry(
            intern_id="CDP-2026-001",
            full_name="Doe, Jane",
            preferred_email="intern@example.com",
            claimed_at=datetime(2026, 6, 1),
            onboarding_completed_at=datetime(2026, 6, 1),
        )
        mock_sheets.return_value.get_track_by_sponsor_email.return_value = None
        mock_sheets.return_value.get_roster_by_email.return_value = mock_entry
        mock_sheets.return_value.update_roster.return_value = True

        response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
        assert response.status_code == 302
        assert "/home" in response.headers["location"]
        assert "session" in response.cookies

    @patch("app.routers.auth.get_sheets_client")
    def test_unclaimed_intern_redirects_to_claim(self, mock_sheets, client):
        """Unknown email redirects to /claim."""
        from app.services.tokens import create_magic_token

        token = create_magic_token("new@example.com")
        mock_sheets.return_value.get_track_by_sponsor_email.return_value = None
        mock_sheets.return_value.get_roster_by_email.return_value = None

        response = client.get(f"/auth/verify?token={token}", follow_redirects=False)
        assert response.status_code == 302
        assert "/claim" in response.headers["location"]


class TestLogout:
    """Tests for logout."""

    def test_logout_clears_session(self, client):
        """Logout clears session cookie."""
        from app.services.sessions import create_session_token

        token = create_session_token("test@example.com", "CDP-001", "intern")
        response = client.post(
            "/auth/logout",
            cookies={"session": token},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "/" == response.headers["location"]

    def test_logout_get_works(self, client):
        """GET logout also works."""
        response = client.get("/auth/logout", follow_redirects=False)
        assert response.status_code == 302
