from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def _read_version() -> str:
    try:
        v = _VERSION_FILE.read_text().strip()
        return v if v else "dev"
    except FileNotFoundError:
        return "dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Cyber Defenders Program — Intern Portal"
    version: str = _read_version()
    env: str = "development"
    log_level: str = "INFO"

    # Security
    secret_key: str = "change-me-in-production"
    base_url: str = "http://localhost:8001"

    # Admin emails (comma-separated)
    admin_emails: str = ""

    # Google Sheets
    google_sheets_id: str = ""
    applicant_sheets_id: str = ""
    google_service_account_path: str = "/etc/internapp/service-account.json"

    # Forward Email API (preferred)
    forwardemail_api_url: str = "https://api.forwardemail.net/v1/emails"
    forwardemail_user: str = ""
    forwardemail_pass: str = ""

    # SMTP fallback (kept for reference, not used)
    smtp_host: str = "smtp.forwardemail.net"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""

    # Magic link settings
    magic_link_ttl_minutes: int = 15
    rate_limit_per_email_15m: int = 10

    # Discord bot token (used as BOT_API_KEY for OpenClaw → FastAPI auth)
    discord_cdpbot_token: str = ""

    # Linear
    linear_api_key: str = ""
    linear_team_id: str = "9e576d33-679d-4268-ad77-360ff1d71ca8"
    linear_webhook_secret: str = ""

    # SQLite
    sqlite_path: str = "data/app.db"

    # Port
    port: int = 8001

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @property
    def admin_email_list(self) -> list[str]:
        """Return list of admin emails (lowercased)."""
        if not self.admin_emails:
            return []
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


settings = Settings()
