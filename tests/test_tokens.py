"""Tests for magic token service."""

import uuid

import pytest

from app.db.sqlite import init_db
from app.services.tokens import (
    check_rate_limit,
    cleanup_expired_tokens,
    create_magic_token,
    validate_magic_token,
)


@pytest.fixture(autouse=True)
def setup_db(setup_test_env):
    """Initialize database before each test."""
    init_db()


class TestMagicTokens:
    """Tests for magic token creation and validation."""

    def test_create_and_validate_token(self):
        """Token can be created and validated."""
        email = "test@example.com"
        token = create_magic_token(email)

        assert token is not None
        assert len(token) > 20

        validated_email = validate_magic_token(token)
        assert validated_email == email

    def test_token_single_use(self):
        """Token can only be used once."""
        email = "single@example.com"
        token = create_magic_token(email)

        assert validate_magic_token(token) == email
        assert validate_magic_token(token) is None

    def test_token_expiry(self):
        """Expired token is rejected."""
        email = "expired@example.com"
        token = create_magic_token(email, ttl_minutes=-1)
        assert validate_magic_token(token) is None

    def test_invalid_token(self):
        """Random string is rejected."""
        assert validate_magic_token("invalid-token-string") is None
        assert validate_magic_token("") is None

    def test_email_normalized_to_lowercase(self):
        """Email is normalized to lowercase."""
        token = create_magic_token("TEST@EXAMPLE.COM")
        email = validate_magic_token(token)
        assert email == "test@example.com"


class TestRateLimiting:
    """Tests for rate limiting (limit is 10 per 15 min)."""

    def test_first_request_allowed(self):
        """First request is always allowed."""
        email = f"new-{uuid.uuid4()}@example.com"
        allowed, count = check_rate_limit(email)
        assert allowed is True
        assert count == 1

    def test_under_limit_allowed(self):
        """Requests under 10 limit are all allowed."""
        email = f"limited-{uuid.uuid4()}@example.com"

        for i in range(9):
            allowed, count = check_rate_limit(email)
            assert allowed is True
            assert count == i + 1

    def test_at_limit_allowed(self):
        """10th request is still allowed."""
        email = f"atlimit-{uuid.uuid4()}@example.com"

        for _ in range(9):
            check_rate_limit(email)

        allowed, count = check_rate_limit(email)
        assert allowed is True
        assert count == 10

    def test_over_limit_rejected(self):
        """11th request is rejected (limit is 10)."""
        email = f"overlimit-{uuid.uuid4()}@example.com"

        for _ in range(10):
            check_rate_limit(email)

        allowed, count = check_rate_limit(email)
        assert allowed is False
        assert count == 10

    def test_different_emails_independent(self):
        """Rate limits are per-email, not global."""
        email1 = f"indep1-{uuid.uuid4()}@example.com"
        email2 = f"indep2-{uuid.uuid4()}@example.com"

        for _ in range(10):
            check_rate_limit(email1)

        # email2 should not be affected
        allowed, count = check_rate_limit(email2)
        assert allowed is True
        assert count == 1


class TestCleanup:
    """Tests for token cleanup."""

    def test_cleanup_expired_tokens(self):
        """Cleanup marks expired tokens and deletes old ones."""
        create_magic_token("cleanup@example.com", ttl_minutes=-1)
        cleaned = cleanup_expired_tokens()
        assert cleaned >= 1
