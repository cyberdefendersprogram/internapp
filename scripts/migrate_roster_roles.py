#!/usr/bin/env python3
"""
Add a 'role' column to the Roster sheet and backfill existing rows with 'intern'.

Safe to run on a sheet with real data — appends the column at the end
rather than inserting it mid-table (which would shift existing data).

Usage:
    GOOGLE_SHEETS_ID=... GOOGLE_SERVICE_ACCOUNT_PATH=... python scripts/migrate_roster_roles.py

Or via make:
    make migrate-roles
"""

import os
import sys
from pathlib import Path


def get_client():
    import gspread
    from google.oauth2.service_account import Credentials

    sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
    if not Path(sa_path).exists():
        print(f"ERROR: Service account not found: {sa_path}", file=sys.stderr)
        sys.exit(1)

    creds = Credentials.from_service_account_file(
        sa_path, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)


def main():
    sheets_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheets_id:
        print("ERROR: GOOGLE_SHEETS_ID not set", file=sys.stderr)
        sys.exit(1)

    client = get_client()
    spreadsheet = client.open_by_key(sheets_id)
    ws = spreadsheet.worksheet("Roster")

    headers = ws.row_values(1)
    if not headers:
        print("ERROR: Roster sheet appears empty (no headers in row 1).")
        sys.exit(1)

    print(f"Current headers ({len(headers)}): {headers}")

    if "role" in headers:
        role_col = headers.index("role") + 1  # 1-based
        print(f"'role' column already exists at column {role_col}. Checking for blank values…")
    else:
        # Append 'role' header after the last existing column
        role_col = len(headers) + 1
        ws.update_cell(1, role_col, "role")
        print(f"Added 'role' header at column {role_col}.")

    # Fetch all data rows (gspread get_all_values gives raw rows, no header mapping)
    all_rows = ws.get_all_values()
    data_rows = all_rows[1:]  # skip header

    updated = 0
    for i, row in enumerate(data_rows):
        sheet_row = i + 2  # 1-based, +1 for header

        # Skip completely empty rows
        if not any(cell.strip() for cell in row):
            continue

        # Read current role value (may not exist if row is shorter than role_col)
        current_role = row[role_col - 1].strip() if len(row) >= role_col else ""

        if not current_role:
            intern_id = row[0].strip() if row else ""
            ws.update_cell(sheet_row, role_col, "intern")
            print(f"  Row {sheet_row} ({intern_id or 'unknown'}): set role = intern")
            updated += 1
        else:
            intern_id = row[0].strip() if row else ""
            print(f"  Row {sheet_row} ({intern_id}): already has role = {current_role!r} — skipped")

    print(f"\nDone. {updated} row(s) updated.")
    print("\nValid roles: intern, mentor, admin, sponsor")
    print("To assign a role, edit the 'role' cell in the Roster sheet. No code changes needed.")
    print("IMPORTANT: For mentor/admin/sponsor rows, also pre-populate 'preferred_email' —")
    print("these roles do not go through the intern claim flow.")


if __name__ == "__main__":
    main()
