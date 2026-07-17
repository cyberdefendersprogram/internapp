#!/usr/bin/env python3
"""
Seed script for internapp Google Sheets.

Creates all required tabs with correct headers and sample Config rows.

Usage:
    python scripts/seed_sheets.py --create-structure

Environment variables:
    GOOGLE_SHEETS_ID            Target spreadsheet ID
    GOOGLE_SERVICE_ACCOUNT_PATH Path to service account JSON file
"""

import argparse
import os
import sys
from pathlib import Path


def get_client():
    """Initialize gspread client."""
    import gspread
    from google.oauth2.service_account import Credentials

    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH", "")
    if not sa_path or not Path(sa_path).exists():
        print(f"ERROR: Service account file not found: {sa_path}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_service_account_file(
        sa_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds)


def get_or_create_worksheet(spreadsheet, name: str, rows: int = 1000, cols: int = 26):
    """Get existing worksheet or create new one. Case-insensitive lookup; renames if casing differs."""
    all_ws = spreadsheet.worksheets()
    by_title = {ws.title: ws for ws in all_ws}

    # Exact match
    if name in by_title:
        print(f"  Found existing tab: {name}")
        return by_title[name]

    # Case-insensitive match — rename to canonical casing
    for title, ws in by_title.items():
        if title.lower() == name.lower():
            ws.update_title(name)
            print(f"  Renamed tab '{title}' → '{name}'")
            return ws

    # Not found — create it
    ws = spreadsheet.add_worksheet(title=name, rows=rows, cols=cols)
    print(f"  Created new tab: {name}")
    return ws


def ensure_headers(ws, headers: list[str]):
    """Set header row if not already set correctly."""
    existing = ws.row_values(1)
    if existing != headers:
        ws.update([headers], range_name="A1")
        print(f"    Set headers: {headers}")
    else:
        print("    Headers already correct.")


def _cdp_2026_tracks() -> list[list]:
    """Return the 7 official CDP 2026 tracks as sheet rows."""
    # [track_id, name, description, employer_sponsor, sponsor_email, status]
    return [
        [
            "track-1",
            "Malware Copilot: AI-Assisted Reverse Engineering Lab",
            "Build Model Context Protocol tools for malware analysis agents. Integrate tools into agent frameworks, analyze malware samples from basic to advanced scenarios, and benchmark different models and configurations for quality, speed, and cost.",
            "",
            "",
            "active",
        ],
        [
            "track-2",
            "Secure the Mission: Nonprofit Security Assessment Lab",
            "Conduct technical security reviews for community organizations, creating prioritized, plain-language recommendations that nonprofit staff can act on and delivering professional assessment reports for stakeholders.",
            "",
            "",
            "active",
        ],
        [
            "track-3",
            "Trust but Verify: SOC 2 Audit Readiness",
            "Support live compliance programs at Interlaced by mapping controls to SOC 2 criteria, remediating policy gaps, collecting audit evidence, and maintaining risk registers and remediation trackers.",
            "Troy Mason",
            "troy.mason@interlaced.com",
            "active",
        ],
        [
            "track-4",
            "Lens Check: IoT Camera Privacy Lab",
            "Analyze consumer IoT devices' firmware, network communications, and cloud connections. Document privacy and security risks, and create consumer-focused recommendations and responsible disclosure templates.",
            "",
            "",
            "active",
        ],
        [
            "track-5",
            "Ghost Cloud: LLM Honeypots in AWS",
            "Build deception environments using Beelzebub to collect attacker telemetry, commands, and indicators while maintaining safety guardrails on real AWS infrastructure.",
            "",
            "",
            "active",
        ],
        [
            "track-6",
            "Signal in the Noise: Threat Intel for Community Defenders",
            "Research threat actors and campaigns, map tactics to MITRE ATT&CK, and deliver practical defensive guidance for small organizations.",
            "",
            "",
            "active",
        ],
        [
            "track-7",
            "Prompt to Pentest: LLM-Assisted Security Testing Lab",
            "Use LLMs for vulnerability discovery, scanner analysis, and pentesting tool development in controlled environments with documented safety boundaries.",
            "",
            "",
            "active",
        ],
    ]


def update_tracks(spreadsheet):
    """Replace Tracks sheet with the 7 official CDP 2026 tracks and remap Roster track IDs."""
    tracks_ws = spreadsheet.worksheet("Tracks")

    # Map old track IDs → new track IDs based on topic alignment
    track_id_remap = {
        "track-8": "track-1",  # Malware Analysis → Malware Copilot
        "track-7": "track-2",  # Non profit risk → Secure the Mission (Nonprofit)
        "track-9": "track-3",  # Trust but Verify SOC 2 (already correct name, renumber)
        "track-3": "track-4",  # Vulnerability Research → Lens Check (IoT)
        "track-2": "track-5",  # Cloud Security (AWS Honeypot) → Ghost Cloud
        "track-1": "track-6",  # Threat Intelligence → Signal in the Noise
        "track-6": "track-7",  # Pentesting → Prompt to Pentest
    }

    # Clear existing track rows (keep header)
    all_values = tracks_ws.get_all_values()
    if len(all_values) > 1:
        tracks_ws.delete_rows(2, len(all_values))

    new_tracks = _cdp_2026_tracks()
    tracks_ws.append_rows(new_tracks, value_input_option="RAW")
    print(f"[Tracks] Replaced with {len(new_tracks)} CDP 2026 tracks.")

    # Remap Roster track_ids
    roster_ws = spreadsheet.worksheet("Roster")
    roster_headers = roster_ws.row_values(1)
    if "track_id" not in roster_headers:
        print("[Roster] track_id column not found — skipping remap.")
        return

    track_id_col = roster_headers.index("track_id") + 1  # 1-indexed
    all_roster = roster_ws.get_all_values()
    remapped = 0
    unmapped = []

    for row_idx, row in enumerate(all_roster[1:], start=2):
        if len(row) < track_id_col:
            continue
        old_id = row[track_id_col - 1]
        if old_id in track_id_remap:
            new_id = track_id_remap[old_id]
            roster_ws.update_cell(row_idx, track_id_col, new_id)
            intern_id = row[0] if row else "?"
            print(f"  Roster row {row_idx} ({intern_id}): {old_id} → {new_id}")
            remapped += 1
        elif old_id and old_id not in {f"track-{i}" for i in range(1, 8)}:
            intern_id = row[0] if row else "?"
            unmapped.append(f"  {intern_id}: track_id='{old_id}' (no mapping defined)")

    print(f"[Roster] Remapped {remapped} rows.")
    if unmapped:
        print("[Roster] WARNING — rows with unrecognized track IDs (manual review needed):")
        for u in unmapped:
            print(u)


def create_structure(spreadsheet):
    """Create all 8 tabs with correct headers."""

    tabs = {
        "Roster": [
            "intern_id",
            "full_name",
            "track_id",
            "role",
            "preferred_email",
            "preferred_name",
            "school",
            "year",
            "linkedin",
            "github",
            "bio",
            "claimed_at",
            "onboarding_completed_at",
            "last_login_at",
            "discord_id",
            "discord_notify",
            "cal_link",
            "linear_user_id",
            "student_reviewer",
        ],
        "Tracks": [
            "track_id",
            "name",
            "description",
            "employer_sponsor",
            "sponsor_email",
            "status",
        ],
        "Check_ins": [
            "submitted_at",
            "intern_id",
            "email",
            "week_number",
            "status_update",
            "blockers",
            "next_steps",
        ],
        "Deliverables": [
            "submitted_at",
            "intern_id",
            "track_id",
            "week_number",
            "title",
            "url",
            "description",
        ],
        "Attendance": [
            "session_date",
            "session_type",
            "intern_id",
            "present",
            "notes",
        ],
        "Mentor_Feedback": [
            "submitted_at",
            "intern_id",
            "week_number",
            "reviewer_email",
            "rating",
            "feedback",
        ],
        "Peer_Reviews": [
            "submitted_at",
            "reviewer_id",
            "reviewer_name",
            "reviewee_id",
            "reviewee_name",
            "rating",
            "strengths",
            "growth_areas",
            "comments",
        ],
        "Email_Log": [
            "sent_at",
            "sender_email",
            "recipient_email",
            "recipient_name",
            "subject",
            "template",
            "status",
            "note",
            "ip_address",
        ],
        "Config": [
            "key",
            "value",
        ],
        "Tasks": [
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
        ],
        "Task_Templates": [
            "template_id",
            "title",
            "description",
            "task_type",
            "assigned_to",
            "week_number",
            "due_week",
            "priority",
            "linked_feature",
        ],
    }

    for tab_name, headers in tabs.items():
        print(f"\n[{tab_name}]")
        ws = get_or_create_worksheet(spreadsheet, tab_name)
        ensure_headers(ws, headers)

    # Seed Config with defaults if empty
    config_ws = spreadsheet.worksheet("Config")
    existing_records = config_ws.get_all_records()
    existing_keys = {r.get("key") for r in existing_records}

    default_config = [
        ("program_title", "Cyber Defenders Summer 2026"),
        ("program_start_date", "2026-06-15"),
        ("program_weeks", "6"),
        ("magic_link_ttl_minutes", "15"),
        ("rate_limit_per_email_15m", "10"),
        ("mid_program_video_url", "https://youtu.be/UWPSif2RIbE"),
    ]

    rows_to_add = []
    for key, value in default_config:
        if key not in existing_keys:
            rows_to_add.append([key, value])
            print(f"\n[Config] Adding default: {key} = {value}")

    if rows_to_add:
        config_ws.append_rows(rows_to_add, value_input_option="RAW")

    # Seed sample Tracks if empty
    tracks_ws = spreadsheet.worksheet("Tracks")
    existing_tracks = tracks_ws.get_all_records()
    if not existing_tracks:
        print("\n[Tracks] Adding 2026 program tracks...")
        sample_tracks = _cdp_2026_tracks()
        tracks_ws.append_rows(sample_tracks, value_input_option="RAW")

    # Seed sample Roster if empty
    roster_ws = spreadsheet.worksheet("Roster")
    existing_roster = roster_ws.get_all_records()
    if not existing_roster:
        print("\n[Roster] Adding sample interns, mentors, and sponsors...")
        # intern_id, full_name, track_id, role, preferred_email, preferred_name, school, year,
        # linkedin, github, bio, claimed_at, onboarding_completed_at, last_login_at,
        # discord_id, discord_notify
        # NOTE: mentor/admin/sponsor rows must have preferred_email pre-set by admin —
        # they do not go through the intern claim flow.
        sample_roster = [
            # Mentors (preferred_email pre-populated; no claim needed)
            [
                "CDP-2026-M01",
                "Mentor, Jane",
                "track-1",
                "mentor",
                "jane@company.com",
                "Jane",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            [
                "CDP-2026-M02",
                "Mentor, John",
                "track-2",
                "mentor",
                "john@company.com",
                "John",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            # Sponsors (preferred_email pre-populated; no claim needed)
            [
                "CDP-2026-SP01",
                "Sponsor, Alice",
                "track-1",
                "sponsor",
                "alice@company.com",
                "Alice",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            # Interns (preferred_email blank until intern claims their account)
            [
                "CDP-2026-001",
                "Doe, Jane",
                "track-1",
                "intern",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            [
                "CDP-2026-002",
                "Smith, Alex",
                "track-1",
                "intern",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            [
                "CDP-2026-003",
                "Johnson, Sam",
                "track-2",
                "intern",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            [
                "CDP-2026-004",
                "Williams, Taylor",
                "track-2",
                "intern",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
            [
                "CDP-2026-005",
                "Brown, Jordan",
                "track-3",
                "intern",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "true",
            ],
        ]
        roster_ws.append_rows(sample_roster, value_input_option="RAW")

    print("\nDone! Structure created successfully.")


def migrate_roster_discord_columns(spreadsheet):
    """Add discord_id and discord_notify columns to Roster if missing."""
    roster_ws = spreadsheet.worksheet("Roster")
    headers = roster_ws.row_values(1)
    added = []

    if "discord_id" not in headers:
        next_col = len(headers) + 1
        roster_ws.update_cell(1, next_col, "discord_id")
        headers.append("discord_id")
        added.append("discord_id")

    if "discord_notify" not in headers:
        next_col = len(headers) + 1
        roster_ws.update_cell(1, next_col, "discord_notify")
        # Default all existing rows to true
        records = roster_ws.get_all_records()
        col = len(roster_ws.row_values(1))
        for idx in range(len(records)):
            roster_ws.update_cell(idx + 2, col, "true")
        added.append("discord_notify")

    if added:
        print(f"  Added Roster columns: {added}")
    else:
        print("  Roster discord columns already present.")


def migrate_roster_reviewer_column(spreadsheet):
    """Add student_reviewer column to Roster if missing."""
    roster_ws = spreadsheet.worksheet("Roster")
    headers = roster_ws.row_values(1)

    if "student_reviewer" in headers:
        print("  Roster student_reviewer column already present.")
        return

    next_col = len(headers) + 1
    roster_ws.update_cell(1, next_col, "student_reviewer")
    print("  Added Roster column: student_reviewer")


def set_reviewer_assignments(spreadsheet, assignments: dict[str, str]):
    """Write student_reviewer values onto Roster rows, matched by preferred_name.

    assignments: {preferred_name: "Comma, Separated, Reviewee Names"}
    """
    roster_ws = spreadsheet.worksheet("Roster")
    headers = roster_ws.row_values(1)
    if "student_reviewer" not in headers:
        print("ERROR: Roster missing student_reviewer column — run --migrate-reviewer first.")
        return

    col = headers.index("student_reviewer") + 1
    name_col = headers.index("preferred_name") + 1
    records = roster_ws.get_all_values()[1:]

    updated, unmatched = 0, []
    for idx, row in enumerate(records, start=2):
        pref_name = row[name_col - 1].strip() if len(row) >= name_col else ""
        if pref_name in assignments:
            roster_ws.update_cell(idx, col, assignments[pref_name])
            updated += 1

    matched_names = {row[name_col - 1].strip() for row in records if len(row) >= name_col}
    for name in assignments:
        if name not in matched_names:
            unmatched.append(name)

    print(f"[Roster] Set student_reviewer for {updated} rows.")
    if unmatched:
        print(f"[Roster] WARNING — no roster row matched preferred_name for: {unmatched}")


def seed_tasks(spreadsheet, target_email: str = "vaibhavb@gmail.com"):
    """Seed sample Task_Templates and a test task for the given email."""
    import uuid
    from datetime import datetime

    # Seed Task_Templates if empty
    templates_ws = spreadsheet.worksheet("Task_Templates")
    existing = templates_ws.get_all_records()
    if not existing:
        print("\n[Task_Templates] Adding default 6-week task templates...")
        # template_id, title, description, task_type, assigned_to, week_number, due_week, priority, linked_feature
        templates = [
            [
                "tmpl-001",
                "Complete your profile",
                "Fill out all profile fields.",
                "system",
                "all",
                1,
                1,
                "normal",
                "onboarding",
            ],
            [
                "tmpl-002",
                "Submit Week 1 check-in",
                "Submit your first weekly check-in.",
                "system",
                "all",
                1,
                1,
                "normal",
                "checkin",
            ],
            [
                "tmpl-003",
                "Introduce yourself in #general",
                "Post a brief intro in the Discord #general channel.",
                "system",
                "all",
                1,
                1,
                "normal",
                "",
            ],
            [
                "tmpl-004",
                "Join your track channel on Discord",
                "Find and join your track channel.",
                "system",
                "all",
                1,
                1,
                "normal",
                "",
            ],
            ["tmpl-005", "Submit Week 2 check-in", "", "system", "all", 2, 2, "normal", "checkin"],
            [
                "tmpl-006",
                "Schedule 1:1 with mentor",
                "Reach out and schedule your first 1:1.",
                "system",
                "all",
                2,
                2,
                "normal",
                "",
            ],
            ["tmpl-007", "Submit Week 3 check-in", "", "system", "all", 3, 3, "normal", "checkin"],
            [
                "tmpl-008",
                "Submit mid-program deliverable",
                "Submit your Week 3 deliverable on the portal.",
                "system",
                "all",
                3,
                3,
                "high",
                "deliverable",
            ],
            ["tmpl-009", "Submit Week 4 check-in", "", "system", "all", 4, 4, "normal", "checkin"],
            [
                "tmpl-010",
                "Peer review another intern's deliverable",
                "Review and give feedback on a teammate's Week 3 deliverable.",
                "system",
                "all",
                4,
                4,
                "normal",
                "",
            ],
            ["tmpl-011", "Submit Week 5 check-in", "", "system", "all", 5, 5, "normal", "checkin"],
            [
                "tmpl-012",
                "Draft final deliverable outline",
                "Submit a draft or outline of your final deliverable.",
                "system",
                "all",
                5,
                5,
                "normal",
                "deliverable",
            ],
            [
                "tmpl-016",
                "Complete your peer reviews",
                "Review the projects of your assigned peers and submit feedback on the portal.",
                "system",
                "all",
                5,
                5,
                "normal",
                "peer_review",
            ],
            ["tmpl-013", "Submit Week 6 check-in", "", "system", "all", 6, 6, "normal", "checkin"],
            [
                "tmpl-014",
                "Submit final deliverable",
                "Submit your completed final deliverable.",
                "system",
                "all",
                6,
                6,
                "high",
                "deliverable",
            ],
            [
                "tmpl-015",
                "Complete program exit survey",
                "Fill out the end-of-program survey.",
                "system",
                "all",
                6,
                6,
                "normal",
                "",
            ],
        ]
        templates_ws.append_rows(templates, value_input_option="RAW")
        print(f"  Added {len(templates)} templates.")

    # Seed a test task for the target email
    tasks_ws = spreadsheet.worksheet("Tasks")
    roster_ws = spreadsheet.worksheet("Roster")
    roster_records = roster_ws.get_all_records()

    intern_id = None
    for r in roster_records:
        if str(r.get("preferred_email", "")).lower() == target_email.lower():
            intern_id = str(r.get("intern_id"))
            break

    if not intern_id:
        print(f"\n[Tasks] No roster entry found for {target_email} — skipping test task.")
        print("  Tip: Make sure the email is in the Roster sheet with preferred_email set.")
        return

    # Check if test task already exists
    existing_tasks = tasks_ws.get_all_records()
    for t in existing_tasks:
        if str(t.get("assigned_to")) == intern_id and t.get("title") == "Test the tasks feature":
            print(f"\n[Tasks] Test task already exists for {target_email} ({intern_id})")
            return

    task_headers = tasks_ws.row_values(1)
    now = datetime.utcnow().isoformat()
    task_data = {
        "task_id": str(uuid.uuid4())[:8],
        "title": "Test the tasks feature",
        "description": "Run /tasks in Discord or visit /tasks on the web portal to verify the tasks system is working.",
        "task_type": "assigned",
        "assigned_to": intern_id,
        "assigned_by": "system",
        "track_id": "",
        "week_number": 1,
        "due_week": 1,
        "status": "todo",
        "priority": "high",
        "linked_feature": "",
        "source": "system",
        "skip_reason": "",
        "created_at": now,
        "completed_at": "",
    }
    row = [task_data.get(h, "") for h in task_headers]
    tasks_ws.append_row(row, value_input_option="RAW")
    print(f"\n[Tasks] Created test task for {target_email} ({intern_id}): {task_data['task_id']}")


def main():
    parser = argparse.ArgumentParser(description="Seed internapp Google Sheets")
    parser.add_argument(
        "--create-structure",
        action="store_true",
        help="Create all tabs with headers and sample data",
    )
    parser.add_argument(
        "--seed-tasks",
        action="store_true",
        help="Seed Task_Templates and a test task for --email",
    )
    parser.add_argument(
        "--migrate-discord",
        action="store_true",
        help="Add discord_id and discord_notify columns to Roster",
    )
    parser.add_argument(
        "--update-tracks",
        action="store_true",
        help="Replace Tracks sheet with CDP 2026 tracks and remap Roster track IDs",
    )
    parser.add_argument(
        "--migrate-reviewer",
        action="store_true",
        help="Add student_reviewer column to Roster",
    )
    parser.add_argument(
        "--email",
        default="vaibhavb@gmail.com",
        help="Email address to target for test task seeding (default: vaibhavb@gmail.com)",
    )
    args = parser.parse_args()

    if not (
        args.create_structure
        or args.seed_tasks
        or args.migrate_discord
        or args.update_tracks
        or args.migrate_reviewer
    ):
        parser.print_help()
        sys.exit(0)

    sheets_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheets_id:
        print("ERROR: GOOGLE_SHEETS_ID environment variable not set", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to spreadsheet: {sheets_id}")
    client = get_client()
    spreadsheet = client.open_by_key(sheets_id)
    print(f"Opened: {spreadsheet.title}")

    if args.create_structure:
        create_structure(spreadsheet)

    if args.migrate_discord:
        print("\n[Roster] Migrating discord columns...")
        migrate_roster_discord_columns(spreadsheet)

    if args.update_tracks:
        print("\n[Tracks] Updating tracks to CDP 2026 program...")
        update_tracks(spreadsheet)

    if args.migrate_reviewer:
        print("\n[Roster] Migrating student_reviewer column...")
        migrate_roster_reviewer_column(spreadsheet)

    if args.seed_tasks:
        seed_tasks(spreadsheet, target_email=args.email)


if __name__ == "__main__":
    main()
