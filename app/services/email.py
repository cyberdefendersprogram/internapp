"""Email service using Forward Email API (async httpx)."""

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmailResult:
    """Result of sending an email."""

    success: bool
    message_id: str | None = None
    error: str | None = None


async def send_email(
    to: str,
    subject: str,
    html: str | None = None,
    text: str | None = None,
) -> EmailResult:
    """Send an email via Forward Email API."""
    if not settings.forwardemail_user or not settings.forwardemail_pass:
        logger.error("Forward Email credentials not configured")
        return EmailResult(success=False, error="Email not configured")

    payload: dict = {
        "from": settings.forwardemail_user,
        "to": to,
        "subject": subject,
    }
    if html:
        payload["html"] = html
    if text:
        payload["text"] = text

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                settings.forwardemail_api_url,
                auth=(settings.forwardemail_user, settings.forwardemail_pass),
                json=payload,
                timeout=30.0,
            )

        if response.status_code in (200, 201, 202):
            data = response.json()
            message_id = data.get("id") or data.get("message_id")
            logger.info("Email sent to %s (id: %s)", to, message_id)
            return EmailResult(success=True, message_id=message_id)

        error_msg = f"API returned {response.status_code}: {response.text[:200]}"
        logger.error("Failed to send email to %s: %s", to, error_msg)
        return EmailResult(success=False, error=error_msg)

    except httpx.TimeoutException:
        logger.error("Timeout sending email to %s", to)
        return EmailResult(success=False, error="Request timeout")
    except httpx.RequestError as e:
        logger.error("Request error sending email to %s: %s", to, e)
        return EmailResult(success=False, error=str(e))
    except Exception as e:
        logger.exception("Unexpected error sending email to %s", to)
        return EmailResult(success=False, error=str(e))


async def send_magic_link_email(to_email: str, magic_link: str) -> EmailResult:
    """Send a CDP-branded magic link email."""
    subject = "Sign in to Cyber Defenders Program Intern Portal"

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Lato,system-ui,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <tr><td style="background:#062F49;padding:24px 32px;">
          <p style="margin:0;color:#fff;font-family:'Roboto Mono',monospace;font-size:18px;font-weight:700;letter-spacing:1px;">
            Cyber Defenders Program
          </p>
          <p style="margin:4px 0 0;color:#5893BC;font-size:13px;">Intern Portal</p>
        </td></tr>
        <tr><td style="padding:32px;">
          <h2 style="margin:0 0 16px;color:#062F49;font-size:20px;">Sign in to your Intern Portal</h2>
          <p style="color:#555;margin:0 0 24px;line-height:1.6;">
            Click the button below to sign in. This link expires in
            <strong>{settings.magic_link_ttl_minutes} minutes</strong> and can only be used once.
          </p>
          <p style="text-align:center;margin:32px 0;">
            <a href="{magic_link}"
               style="background:#FA7C91;color:#fff;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:700;font-size:16px;display:inline-block;">
              Sign In
            </a>
          </p>
          <p style="color:#777;font-size:13px;margin:0 0 8px;">Or copy this link:</p>
          <p style="background:#f5f5f5;padding:12px;border-radius:4px;font-size:12px;word-break:break-all;color:#333;margin:0;">
            {magic_link}
          </p>
        </td></tr>
        <tr><td style="background:#EFF3F4;padding:16px 32px;text-align:center;">
          <p style="color:#999;font-size:12px;margin:0;">
            If you didn't request this link, you can safely ignore this email.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Cyber Defenders Program — Intern Portal\n\n"
        f"Click the link below to sign in. This link expires in "
        f"{settings.magic_link_ttl_minutes} minutes and can only be used once.\n\n"
        f"{magic_link}\n\n"
        f"If you didn't request this link, you can safely ignore this email."
    )

    return await send_email(to_email, subject, html_body, text_body)


async def send_bulk_email(recipients: list[dict], subject: str, html_body: str) -> dict:
    """
    Send bulk email to multiple recipients.

    Each recipient dict must have an 'email' key.
    Returns {sent: int, failed: int}.
    """
    sent = 0
    failed = 0

    for recipient in recipients:
        to_email = recipient.get("email", "")
        if not to_email:
            failed += 1
            continue

        result = await send_email(to_email, subject, html_body)
        if result.success:
            sent += 1
        else:
            failed += 1
            logger.error("Bulk send failed for %s: %s", to_email, result.error)

    return {"sent": sent, "failed": failed}
