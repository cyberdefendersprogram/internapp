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

Magic link only — no passwords. Three roles:

| Role | How identified | Lands at |
|------|---------------|---------|
| `admin` | Email in `ADMIN_EMAILS` env var | `/admin` |
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
| `APPLICANT_SHEETS_ID` | — | Separate spreadsheet for applicants |
| `MAGIC_LINK_TTL_MINUTES` | `15` | Token expiry |
| `RATE_LIMIT_PER_EMAIL_15M` | `10` | Max magic link requests per email per 15 min window |

### Email

The app sends all email via the **ForwardEmail REST API** (`https://api.forwardemail.net/v1/emails`). Set `FORWARDEMAIL_USER` and `FORWARDEMAIL_PASS` in your `.env`. SMTP variables (`SMTP_HOST`, etc.) are kept in config for reference but are not used.

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

See [DEPLOY.md](DEPLOY.md) for the full setup guide. The short version:

1. Push to `main` — GitHub Actions builds the image, pushes to GHCR, and SSHs to the droplet.
2. The droplet runs `docker compose pull && docker compose up -d`.
3. Secrets live in `/opt/internapp/env/.env` and `/etc/internapp/service-account.json` (mode 600).

```bash
make logs      # tail live container logs
make ssh       # SSH to droplet
make health    # curl /health
make restart   # restart containers
make db-reset  # wipe SQLite (does NOT touch Sheets data)
```

---

## Google Sheets Structure

Single spreadsheet with these tabs: `Roster`, `Tracks`, `Check_ins`, `Deliverables`, `Attendance`, `Mentor_Feedback`, `Email_Log`, `Config`.

The service account (`internapp-sheets@internapp-497708.iam.gserviceaccount.com`) must have **Editor** access to the spreadsheet.

---

## Public Dashboard

`/program` — no auth required. Shows tracks, interns, and deliverable links. Does not expose check-in content, feedback, attendance, ratings, or email addresses.

---

## Full Specification

See [SPEC.md](SPEC.md) for the complete technical and product specification including data models, API routes, UI design, and acceptance criteria.
