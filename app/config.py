from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Cyber Defenders Program — Intern Portal"
    version: str = "1.0.0"
    env: str = "development"
    log_level: str = "INFO"

    # Security
    secret_key: str = "change-me-in-production"
    base_url: str = "http://localhost:8001"

    # Admin emails (comma-separated)
    admin_emails: str = ""

    # Google Sheets
    google_sheets_id: str = ""
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
