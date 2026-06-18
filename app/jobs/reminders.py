"""Scheduled reminder jobs."""

import logging

from app.routers.intern import compute_week_number
from app.services.discord import send_dm
from app.services.sheets import get_sheets_client

logger = logging.getLogger(__name__)


def send_checkin_reminders() -> dict:
    """
    DM every intern who hasn't submitted a check-in for the current week.
    Safe to call multiple times — only sends if genuinely missing.
    Returns a summary dict for logging / admin display.
    """
    sheets = get_sheets_client()
    week_number = compute_week_number(sheets)
    all_roster = sheets.get_all_roster()
    interns = [r for r in all_roster if r.role == "intern" and r.is_claimed]

    sent, skipped, missing_discord = [], [], []

    for intern in interns:
        checkins = sheets.get_checkins_for_intern(intern.intern_id)
        already_in = any(str(c.get("week_number")) == str(week_number) for c in checkins)
        if already_in:
            skipped.append(intern.display_name)
            continue

        if not intern.discord_id:
            missing_discord.append(intern.display_name)
            logger.warning("No discord_id for %s — skipping reminder", intern.intern_id)
            continue

        name = intern.preferred_name or intern.display_name
        msg = (
            f"👋 Hey {name}! Quick reminder — your **Week {week_number} check-in** "
            f"is due today.\n\n"
            f"It only takes a few minutes:\n"
            f"➜ https://intern.cyberdefendersprogram.com/checkin\n\n"
            f"Drop a note on what you worked on, any blockers, and your next steps. "
            f"Your mentor reads these every week!"
        )
        ok = send_dm(intern.discord_id, msg)
        if ok:
            sent.append(intern.display_name)
            logger.info("Check-in reminder sent to %s (week %s)", intern.intern_id, week_number)
        else:
            missing_discord.append(intern.display_name)

    logger.info(
        "Check-in reminders week %s: sent=%d skipped=%d failed=%d",
        week_number,
        len(sent),
        len(skipped),
        len(missing_discord),
    )
    return {
        "week_number": week_number,
        "sent": sent,
        "already_checked_in": skipped,
        "failed": missing_discord,
    }
