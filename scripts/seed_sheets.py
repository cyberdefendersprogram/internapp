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
        "Email_Log": [
            "sent_at",
            "sender_email",
            "recipient_email",
            "recipient_name",
            "subject",
            "template",
            "status",
            "note",
        ],
        "Config": [
            "key",
            "value",
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
        print("\n[Tracks] Adding sample tracks...")
        sample_tracks = [
            [
                "track-1",
                "Threat Intelligence",
                "Research and analyze threat actors and TTPs.",
                "Jane Mentor",
                "jane@company.com",
                "active",
            ],
            [
                "track-2",
                "Cloud Security",
                "Secure cloud infrastructure and review IAM policies.",
                "John Mentor",
                "john@company.com",
                "active",
            ],
            [
                "track-3",
                "Vulnerability Research",
                "Find and document security vulnerabilities.",
                "Alice Mentor",
                "alice@company.com",
                "active",
            ],
            [
                "track-4",
                "Incident Response",
                "Detect, analyze, and respond to security incidents.",
                "Bob Mentor",
                "bob@company.com",
                "active",
            ],
            [
                "track-5",
                "Security Engineering",
                "Build security tooling and automation.",
                "Carol Mentor",
                "carol@company.com",
                "active",
            ],
        ]
        tracks_ws.append_rows(sample_tracks, value_input_option="RAW")

    # Seed sample Roster if empty
    roster_ws = spreadsheet.worksheet("Roster")
    existing_roster = roster_ws.get_all_records()
    if not existing_roster:
        print("\n[Roster] Adding sample interns...")
        # intern_id, full_name, track_id, role, preferred_email, preferred_name, school, year, linkedin, github, bio, claimed_at, onboarding_completed_at, last_login_at
        sample_roster = [
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
            ],
        ]
        roster_ws.append_rows(sample_roster, value_input_option="RAW")

    print("\nDone! Structure created successfully.")


def main():
    parser = argparse.ArgumentParser(description="Seed internapp Google Sheets")
    parser.add_argument(
        "--create-structure",
        action="store_true",
        help="Create all tabs with headers and sample data",
    )
    args = parser.parse_args()

    if not args.create_structure:
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

    create_structure(spreadsheet)


if __name__ == "__main__":
    main()
