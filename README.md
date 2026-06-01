# CDP Intern Portal

Lightweight intern tracking portal for the Cyber Defenders Summer 2026 program. ~25 interns across 5 cybersecurity project tracks. Google Sheets is the system of record; auth state lives in SQLite.

**Live**: https://intern.cyberdefendersprogram.com

---

## Stack

| Layer | Technology |
|-------|-----------|
| App server | FastAPI (Python) |
| Templates | Jinja2 + Bulma CSS |
| Program data | Google Sheets |
| Auth state | SQLite |
| Email | ForwardEmail REST API (`api.forwardemail.net`) |
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
| `DISCORD_CDPBOT_TOKEN` | — | Bot API key — required for Discord bot integration |

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

See [DEPLOY.md](DEPLOY.md) for the full setup guide.

```bash
make logs      # tail live container logs
make ssh       # SSH to droplet
make health    # curl /health
make restart   # restart containers
make db-reset  # wipe SQLite (does NOT touch Sheets data)
```

---

## Google Sheets Structure

Single spreadsheet with these tabs: `Roster`, `Tracks`, `Check_ins`, `Deliverables`, `Attendance`, `Mentor_Feedback`, `Email_Log`, `Config`, `Tasks`, `Task_Templates`.

The service account (`internapp-sheets@internapp-497708.iam.gserviceaccount.com`) must have **Editor** access to the spreadsheet.

### Multi-track mentors and sponsors

The `track_id` column in `Roster` supports comma-separated values for mentors and sponsors who span multiple tracks (e.g., `track-1,track-3`). Intern rows use a single track ID.

### Seeding tasks

```bash
# Create Tasks and Task_Templates sheet structure, then fan out templates to all interns
python scripts/seed_sheets.py --seed-tasks

# Add discord_id and discord_notify columns to an existing Roster sheet
python scripts/seed_sheets.py --migrate-discord
```

---

## Discord Bot Integration

The CDP Discord bot (OpenClaw) communicates with this app via `/api/bot/*` endpoints, authenticated with the `DISCORD_CDPBOT_TOKEN` bearer token.

**Identity linking flow:**
1. Intern runs `/link` in Discord
2. Bot requests a magic link to their program email
3. Intern clicks the link — `/auth/discord-link` writes their Discord ID to the Roster sheet
4. All future bot commands resolve automatically via Discord ID

See `openclaw-prompt.md` for the full bot system prompt and command reference.

---

## Public Dashboard

`/program` — no auth required. Shows tracks, interns, and deliverable links. Does not expose check-in content, feedback, attendance, ratings, or email addresses.

---

## Full Specification

See [SPEC.md](SPEC.md) for the complete technical and product specification including data models, API routes, UI design, and acceptance criteria.
