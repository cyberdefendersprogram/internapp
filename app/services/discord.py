"""Discord bot API helpers — DMs and channel messages via bot token."""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bot {settings.discord_cdpbot_token}",
        "Content-Type": "application/json",
    }


def _open_dm_channel(discord_user_id: str) -> str | None:
    """Create (or fetch existing) DM channel with a user. Returns channel_id or None."""
    resp = httpx.post(
        f"{DISCORD_API}/users/@me/channels",
        json={"recipient_id": str(discord_user_id)},
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code in (200, 201):
        return resp.json()["id"]
    logger.error("Discord open_dm(%s) failed %s: %s", discord_user_id, resp.status_code, resp.text)
    return None


def send_dm(discord_user_id: str, message: str) -> bool:
    """Send a DM to a Discord user. Returns True on success."""
    if not settings.discord_cdpbot_token:
        logger.warning("DISCORD_CDPBOT_TOKEN not set — skipping DM to %s", discord_user_id)
        return False

    channel_id = _open_dm_channel(discord_user_id)
    if not channel_id:
        return False

    resp = httpx.post(
        f"{DISCORD_API}/channels/{channel_id}/messages",
        json={"content": message},
        headers=_headers(),
        timeout=10,
    )
    if resp.status_code == 200:
        logger.info("Discord DM sent to user %s", discord_user_id)
        return True
    logger.error("Discord send_dm(%s) failed %s: %s", discord_user_id, resp.status_code, resp.text)
    return False


def send_webhook(webhook_url: str, message: str) -> bool:
    """POST a plain message to a Discord webhook URL."""
    resp = httpx.post(webhook_url, json={"content": message}, timeout=10)
    if resp.status_code in (200, 204):
        return True
    logger.error("Discord webhook failed %s: %s", resp.status_code, resp.text)
    return False
