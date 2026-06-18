# CDP Intern Portal

Lightweight intern tracking portal for the Cyber Defenders Summer 2026 program. ~25 interns across 7 cybersecurity project tracks. Google Sheets is the system of record; auth/notes/issue cache live in SQLite.

**Live**: https://intern.cyberdefendersprogram.com

---

## Stack

| Layer | Technology |
|-------|-----------|
| App server | FastAPI (Python) |
| Templates | Jinja2 + Bulma CSS |
| Program data | Google Sheets |
| Auth / notes / issue cache | SQLite |
| Email | ForwardEmail REST API (`api.forwardemail.net`) |
| Task tracking | Linear (GraphQL API + webhooks) |
| Notifications | Discord Bot API v10 (DMs) |
| Scheduler | APScheduler (Thursday check-in reminders) |
| Runtime | Docker |
| Hosting | DigitalOcean droplet (shared with classapp, port 8001) |
| TLS / proxy | Nginx + Certbot |
| CI/CD | GitHub Actions → GHCR → SSH deploy |

---

## Auth

Magic link only — no passwords. Four roles:

| Role | How identified | Lands at |
|------|---------------|---------|
| `admin` | Email in `ADMIN_EMAILS` env var | `/admin` |
| `mentor` | Roster row with `role=mentor` | `/admin` |
| `sponsor` | Email matches a `sponsor_email` in Tracks sheet | `/sponsor` |
| `intern` | Email claimed against a Roster row | `/home` |

New interns enter their `intern_id` to claim their account, then complete onboarding.

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | JWT signing key (32+ chars) |
| `GOOGLE_SHEETS_ID` | Main program spreadsheet ID |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | Path to service account JSON |
| `FORWARDEMAIL_USER` | ForwardEmail API username (your sending email address) |
| `FORWARDEMAIL_PASS` | ForwardEmail API key / password |
| `BASE_URL` | Public URL, no trailing slash (e.g. `https://intern.cyberdefendersprogram.com`) |
| `ADMIN_EMAILS` | Comma-separated admin email addresses |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `development` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SQLITE_PATH` | `data/app.db` | SQLite database path |
| `PORT` | `8001` | HTTP port inside container |
| `MAGIC_LINK_TTL_MINUTES` | `15` | Token expiry |
| `RATE_LIMIT_PER_EMAIL_15M` | `10` | Max magic link requests per email per 15 min window |
| `DISCORD_CDPBOT_TOKEN` | — | Discord bot token — required for DM reminders and bot commands |
| `LINEAR_API_KEY` | — | Linear personal API key — required for issue sync and assignment |
| `LINEAR_WEBHOOK_SECRET` | — | Linear webhook signing secret — required to verify incoming webhooks |
| `LINEAR_TEAM_ID` | `9e576d33-...` | Linear team ID (pre-set, change only if team changes) |

---

## Local Development

```bash
# Copy and edit the env file
cp .env.example .env   # edit FORWARDEMAIL_USER, FORWARDEMAIL_PASS, GOOGLE_SHEETS_ID, etc.

# Start with Docker Compose
docker compose -f docker-compose.dev.yml up

# Or run directly (requires uv)
uv run uvicorn app.main:app --reload --port 8001
```

App is at http://localhost:8001. Health check: http://localhost:8001/health.

---

## Deployment

Push to `main` — GitHub Actions builds the image, pushes to GHCR, and SSHs to the droplet.
The droplet runs `docker compose pull && docker compose up -d`.

To update a single env var on prod without pushing code:

```
GitHub → Actions → "Update prod .env" → Run workflow → enter KEY and VALUE
```

See [DEPLOY.md](DEPLOY.md) for the full setup guide.

```bash
make logs      # tail live container logs
make ssh       # SSH to droplet
make health    # curl /health
make restart   # restart containers
make db-reset  # wipe SQLite (does NOT touch Sheets data)
make db-tables # list tables in production SQLite
make db-query Q="SELECT COUNT(*) FROM linear_issues"  # run arbitrary SQL on prod
make db-pull   # download prod SQLite to /tmp/internapp-prod.db
```

---

## Google Sheets Structure

Single spreadsheet with these tabs: `Roster`, `Tracks`, `Check_ins`, `Deliverables`, `Mentor_Feedback`, `Email_Log`, `Config`, `Task_Templates`.

The service account (`internapp-sheets@internapp-497708.iam.gserviceaccount.com`) must have **Editor** access to the spreadsheet.

### Key Roster columns

| Column | Who sets it | Notes |
|--------|-------------|-------|
| `intern_id` | Admin | e.g. `CDP-2026-I10` |
| `role` | Admin | `intern`, `mentor`, `admin`, `sponsor` |
| `preferred_email` | Intern (on claim) | Blank until claimed for interns; pre-set for others |
| `track_id` | Admin | Single for interns; comma-separated for multi-track mentors |
| `cal_link` | Mentor row | "Book with Mentor" button on intern home |
| `discord_id` | Set via `/link` flow | Required for DM reminders |
| `discord_notify` | Intern preference | `true` by default |
| `linear_user_id` | Set via admin sync | Linear UUID — populated after intern accepts Linear invite |

### Scheduling links

| Sheet | Column | Effect |
|-------|--------|--------|
| Roster | `cal_link` | "Book with Mentor" button on intern `/home` (all mentors mentor all tracks) |
| Tracks | `sponsor_cal_link` | "Book with Sponsor" button on intern `/home` |

### Meeting notes

Mentors and admins can add meeting notes per intern at `/admin/intern/{id}`. Notes have:
- **Type**: `mentor_1on1`, `sponsor_checkin`, or `other`
- **Visibility**: `all` (intern + sponsor can read) or `mentor_admin` (private)

Notes are stored in SQLite (not Sheets) because Sheets handles multi-line text poorly.

---

## Linear Integration

Interns' program tasks are managed as issues in Linear. The portal bridges Linear ↔ intern identities.

### Setup flow

1. Admin invites interns to the Linear workspace by email.
2. Interns accept the invite (they sign up with their program email).
3. Admin clicks **"Sync Linear IDs"** on `/admin/linear` — this looks up each intern by email in Linear and saves their `linear_user_id` to the Roster.
4. Admin clicks **"Fix assignees"** — this patches any existing unassigned issues to the correct intern.
5. Going forward, issues created via Task Templates are automatically assigned.

### Webhook → Discord DMs

Linear webhooks fire when issues are assigned, completed, or commented on. The webhook receiver at `POST /api/linear/webhook` sends a Discord DM to the relevant intern:

| Event | DM sent |
|-------|---------|
| Issue assigned | "📋 You've been assigned a new task in Linear" |
| Issue completed by mentor/admin | "✅ Your Linear task was marked done" |
| Comment on intern's issue | "💬 New comment on your Linear task" |

The webhook secret (`LINEAR_WEBHOOK_SECRET`) must match the secret configured in the Linear workspace webhook settings.

### Admin routes

| Route | What it does |
|-------|-------------|
| `GET /admin/linear` | Overview: all interns, their issues, and assignment status |
| `POST /admin/linear/sync-ids` | Look up interns by email in Linear, save `linear_user_id` to Roster |
| `POST /admin/linear/fix-assignees` | Patch unassigned Linear issues to the correct intern |
| `POST /api/linear/issues/{id}/done` | Intern marks their issue Done (intern-facing) |

---

## Discord Bot Integration

The CDP Discord bot (OpenClaw) communicates with this app via `/api/bot/*` endpoints, authenticated with the `DISCORD_CDPBOT_TOKEN` bearer token.

### Identity linking flow
1. Intern runs `/link` in Discord
2. Bot requests a magic link to their program email
3. Intern clicks the link — `/auth/discord-link` writes their Discord ID to the Roster sheet
4. All future DMs and bot commands resolve automatically via Discord ID

### Automated DM reminders
Every Thursday at noon PT, the app DMsevery intern who hasn't submitted a check-in for the current week:

> 👋 Hey {name}! Quick reminder — your **Week {week_number} check-in** is due today.
> ➜ https://intern.cyberdefendersprogram.com/checkin

Admins can also trigger reminders manually from `/admin` → "Send Reminders" button.

### Admin Discord routes

| Route | What it does |
|-------|-------------|
| `POST /admin/discord/send-reminders` | Manually trigger check-in DMs to interns who haven't checked in |

See `openclaw-prompt.md` for the full bot system prompt and command reference.

---

## Public Dashboard

`/program` — no auth required. Shows tracks, interns (claimed only), and deliverable links. Does not expose check-in content, feedback, ratings, or email addresses. Sponsor name is hidden if blank or TBD.

---

## Full Specification

See [SPEC.md](SPEC.md) for the complete technical and product specification including data models, API routes, UI design, and acceptance criteria.
