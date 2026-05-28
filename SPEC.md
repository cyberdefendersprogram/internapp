# Intern App — Technical & Product Specification

**Version**: 1.0
**Stack**: FastAPI + Google Sheets + SQLite + Docker + DigitalOcean
**Program**: Cyber Defenders Summer 2026 Internship

---

## 1. Purpose

A lightweight intern tracking portal for ~25 interns across 5 cybersecurity project tracks. Coordinator, sponsors, and interns each have role-appropriate views. Google Sheets is the system of record; auth state lives in SQLite.

**Goals**:
- Track weekly check-ins, deliverables, attendance, and mentor feedback
- Allow coordinator to send templated email reminders to interns or track groups
- Surface a public read-only dashboard of tracks, interns, and deliverables
- Tracks and sponsor info managed in Google Sheets — no code changes needed to update them
- ~$0 additional infrastructure cost, co-hosted with classapp on existing droplet

---

## 2. Design Principles

| Principle | Description |
|-----------|-------------|
| Sheets-first | Google Sheets is the primary database for all program data |
| Role-aware | Three auth tiers: intern, admin, sponsor |
| Human-readable | Coordinator can inspect all state manually in Sheets |
| Low friction | Magic link auth, no passwords |
| Brand-consistent | Matches Cyber Defenders Program visual identity |
| Debuggable | Everything accessible via SSH |

---

## 3. Architecture

### 3.1 Runtime Topology

```
Browser
    │
    ▼ HTTPS :443
┌─────────────────────┐
│  Nginx (host)       │  ← TLS termination, routes intern.* subdomain
└─────────────────────┘
    │ HTTP :8001 (localhost)
    ▼
┌─────────────────────┐
│  Docker container   │
│  ┌───────────────┐  │
│  │   FastAPI     │  │
│  └───────────────┘  │
│         │           │
│    ┌────┴────┐      │
│    ▼         ▼      │
│  SQLite   Sheets    │
└─────────────────────┘
```

Co-hosted with classapp on the same DigitalOcean droplet. classapp runs on port 8000; internapp runs on port 8001. Nginx routes `intern.cyberdefendersprogram.com` to port 8001.

### 3.2 Components

| Component | Purpose |
|-----------|---------|
| Nginx (host) | TLS termination, reverse proxy, subdomain routing |
| Docker | Runtime isolation |
| FastAPI | Application server |
| SQLite | Magic tokens, rate limits, sessions |
| Google Sheets | All program data (roster, tracks, check-ins, deliverables, etc.) |
| GitHub Actions | CI/CD pipeline |
| ForwardEmail API | Magic links + email reminders (`api.forwardemail.net/v1/emails`) |

---

## 4. Environment Variables

### 4.1 Required

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing key (32+ chars) | `your-secret-key-here` |
| `GOOGLE_SHEETS_ID` | Spreadsheet ID from URL | `1BxiMVs0XRA5nFMdKvBd...` |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | Path to service account JSON | `/etc/internapp/sa.json` |
| `FORWARDEMAIL_USER` | ForwardEmail API username (sending address) | `noreply@cyberdefendersprogram.com` |
| `FORWARDEMAIL_PASS` | ForwardEmail API key | `your-api-key` |
| `BASE_URL` | Public URL (no trailing slash) | `https://intern.cyberdefendersprogram.com` |
| `ADMIN_EMAILS` | Comma-separated admin email list | `vaibhavb@gmail.com` |

### 4.2 Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `ENV` | `production` | `development` or `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SQLITE_PATH` | `/var/lib/internapp/app.db` | SQLite database path |
| `PORT` | `8001` | HTTP port inside container |

---

## 5. Hosting

### 5.1 DigitalOcean Droplet (shared with classapp)

| Spec | Value |
|------|-------|
| Type | Basic Droplet (existing) |
| vCPU | 1 |
| RAM | 1 GiB |
| OS | Ubuntu 24.04 LTS |
| Additional cost | $0 (shared with classapp) |

Peak concurrent users expected: **25**.

### 5.2 Directory Structure (on droplet)

```
/opt/internapp/          # Application root
├── docker-compose.yml
└── env/
    └── .env

/var/lib/internapp/      # Persistent data
└── app.db               # SQLite database

/etc/internapp/          # Secrets
└── service-account.json
```

---

## 6. Deployment

### 6.1 Continuous Deployment

On every push to `main`:

```
GitHub Actions
    │
    ├─► Build Docker image
    ├─► Push to GHCR
    ├─► SSH to droplet
    ├─► docker compose pull
    └─► docker compose up -d
```

### 6.2 Nginx Config (addendum to existing classapp config)

```nginx
server {
    listen 80;
    server_name intern.cyberdefendersprogram.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name intern.cyberdefendersprogram.com;

    ssl_certificate /etc/letsencrypt/live/intern.cyberdefendersprogram.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/intern.cyberdefendersprogram.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 7. Authentication & Authorization

### 7.1 Role Model

| Role | How Identified | Access |
|------|---------------|--------|
| `admin` | Email in `ADMIN_EMAILS` env var | Full access to all data and admin routes |
| `sponsor` | Email matches a `sponsor_email` in Tracks sheet | Read own track's interns; submit feedback |
| `intern` | Email claimed against a Roster row | Own check-ins, deliverables, profile |

Role is determined at login time and stored in the JWT payload. Admins and sponsors do not go through the claim flow.

### 7.2 Authentication Flow

```
User enters email
    │
    ▼
Magic link sent (15 min TTL)
    │
    ▼
User clicks link
    │
    ├── Admin email (ADMIN_EMAILS) → session with role=admin → /admin
    ├── Sponsor email (Tracks sheet) → session with role=sponsor → /sponsor
    ├── Intern email already claimed → session with role=intern → /home
    └── Email not found
            │
            ▼
        Enter intern_id
            │
            ▼
        Bind email → onboarding → /home

Unknown emails not in any list get a "not enrolled" message.
```

### 7.3 Session Management

| Property | Value |
|----------|-------|
| Storage | HTTP-only secure cookie |
| Format | Signed JWT |
| Cookie name | `session` |
| TTL | 7 days |
| JWT payload | `{email, intern_id, role, exp}` |

### 7.4 Rate Limiting

Magic link requests are rate-limited generously to avoid blocking legitimate users (prior classapp experience showed tight limits caused problems with shared IPs and slow email clients).

| Limit | Value |
|-------|-------|
| Requests per email per 15 min | **10** |
| Requests per IP per 15 min | **20** |

### 7.5 Security Properties

- No passwords stored
- Magic tokens: one-time use, 15 min TTL
- Intern ID required for initial claim (must exist in Roster)
- Sponsors and admins: email must already be in Tracks sheet or `ADMIN_EMAILS`
- All traffic over TLS

---

## 8. Google Sheets Data Model

Single spreadsheet with these tabs:

### 8.1 `Roster`

One row per intern. Admin pre-populates `intern_id`, `full_name`, `track_id`. Remaining fields filled by interns during onboarding.

| Column | Type | Source |
|--------|------|--------|
| `intern_id` | string | Admin (e.g., `CDP-2026-001`) |
| `full_name` | string | Admin (e.g., `Bhandari, Vaibhav`) |
| `track_id` | string | Admin (e.g., `track-1`) |
| `preferred_email` | string | Intern (set on claim, immutable after) |
| `preferred_name` | string | Intern (optional) |
| `school` | string | Intern |
| `year` | string | Intern (`Freshman`, `Sophomore`, etc.) |
| `linkedin` | string | Intern (optional) |
| `github` | string | Intern (optional) |
| `bio` | string | Intern (short intro, optional) |
| `claimed_at` | ISO timestamp | System |
| `onboarding_completed_at` | ISO timestamp | System |
| `last_login_at` | ISO timestamp | System |

**Constraints**:
- `intern_id` must be unique
- `preferred_email` blank until claimed, immutable after
- `track_id` must match a `track_id` in the `Tracks` sheet

### 8.2 `Tracks`

One row per project track. Admin manages this directly in Sheets; no code changes required to add, rename, or reassign tracks.

| Column | Type | Description |
|--------|------|-------------|
| `track_id` | string | Unique key (e.g., `track-1`) |
| `name` | string | Display name |
| `description` | string | One-paragraph summary |
| `employer_sponsor` | string | Mentor full name |
| `sponsor_email` | string | Mentor email (used for login identity) |
| `status` | string | `active` or `archived` |

### 8.3 `Check_ins`

Append-only. One row per intern per week submission.

| Column | Type | Description |
|--------|------|-------------|
| `submitted_at` | ISO timestamp | Submission time |
| `intern_id` | string | FK to Roster |
| `email` | string | Intern email |
| `week_number` | integer | Program week (1–6, computed from `program_start_date`) |
| `status_update` | string | What I did this week |
| `blockers` | string | Current blockers (optional) |
| `next_steps` | string | Plan for next week |

### 8.4 `Deliverables`

Append-only. Interns submit links or descriptions of artifacts they produce.

| Column | Type | Description |
|--------|------|-------------|
| `submitted_at` | ISO timestamp | Submission time |
| `intern_id` | string | FK to Roster |
| `track_id` | string | FK to Tracks |
| `week_number` | integer | Program week (1–6) |
| `title` | string | Short artifact name |
| `url` | string | Link to artifact (GitHub, doc, etc.) |
| `description` | string | What it is and how to use it |

### 8.5 `Attendance`

Admin or coordinator fills this. One row per intern per session.

| Column | Type | Description |
|--------|------|-------------|
| `session_date` | ISO date | Date of sync call or in-person session |
| `session_type` | string | `weekly-sync`, `in-person`, `kickoff`, `demo-day` |
| `intern_id` | string | FK to Roster |
| `present` | boolean | `TRUE` / `FALSE` |
| `notes` | string | Optional note |

### 8.6 `Mentor_Feedback`

Sponsor or admin submits. One row per intern per review.

| Column | Type | Description |
|--------|------|-------------|
| `submitted_at` | ISO timestamp | Submission time |
| `intern_id` | string | FK to Roster |
| `week_number` | integer | Program week |
| `reviewer_email` | string | Who submitted |
| `rating` | integer | 1–5 scale |
| `feedback` | string | Qualitative notes |

### 8.7 `Email_Log`

Audit log of all emails sent from the app.

| Column | Type | Description |
|--------|------|-------------|
| `sent_at` | ISO timestamp | Send time |
| `sender_email` | string | Admin who triggered it |
| `recipient_email` | string | Recipient |
| `recipient_name` | string | Display name |
| `subject` | string | Email subject |
| `template` | string | Template slug used |
| `status` | string | `sent` or `failed` |
| `note` | string | Error detail if failed |

### 8.8 `Config`

Key-value configuration. Admin edits directly in Sheets.

| Key | Example Value | Description |
|-----|---------------|-------------|
| `program_title` | `Cyber Defenders Summer 2026` | Displayed in UI headers |
| `program_start_date` | `2026-06-15` | Week 1 start (used to compute `week_number`) |
| `program_weeks` | `6` | Total program duration |
| `magic_link_ttl_minutes` | `15` | Token expiry |
| `rate_limit_per_email_15m` | `10` | Max magic link requests per email per window |

---

## 9. SQLite Data Model

Auth-only. Same patterns as classapp.

### 9.1 `magic_tokens`

```sql
CREATE TABLE magic_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    status TEXT DEFAULT 'pending'  -- pending, used, expired
);
CREATE INDEX idx_tokens_email ON magic_tokens(email);
```

### 9.2 `rate_limits`

```sql
CREATE TABLE rate_limits (
    key TEXT PRIMARY KEY,          -- e.g., "magic:user@example.com" or "ip:1.2.3.4"
    window_start TEXT NOT NULL,
    count INTEGER DEFAULT 1
);
```

---

## 10. Onboarding

### 10.1 Form Fields

Shown after first claim. Only fields that are empty in Roster are shown.

| Field | Type | Label |
|-------|------|-------|
| `preferred_name` | text | Preferred Name |
| `school` | text | School / College |
| `year` | select | Year (`Freshman`, `Sophomore`, `Junior`, `Senior`, `Grad`) |
| `linkedin` | url | LinkedIn Profile URL |
| `github` | url | GitHub Profile URL |
| `bio` | textarea | Short bio (2–3 sentences) |

### 10.2 On Submit

1. Update `Roster` row with submitted fields
2. Set `onboarding_completed_at`
3. Send `welcome` email to intern
4. Invalidate cache for this intern
5. Redirect to `/home`

---

## 11. Email Reminders

Admin can compose and send templated emails to any subset of interns directly from the app. All sends are logged to the `Email_Log` sheet.

### 11.1 Audience Options

| Audience | Description |
|----------|-------------|
| All active interns | Everyone with `preferred_email` set |
| By track | All interns assigned to a specific track |
| Missing check-in | Interns who have not submitted a check-in for the current week |
| Single intern | One specific intern by name |

### 11.2 Email Templates

Stored as Jinja2 files in `content/emails/`. Subject and body are rendered with intern-specific context.

**Context variables available in all templates**:

| Variable | Value |
|----------|-------|
| `{{ intern_name }}` | Preferred name or first name from `full_name` |
| `{{ track_name }}` | Intern's assigned track name |
| `{{ sponsor_name }}` | Track's employer sponsor |
| `{{ week_number }}` | Current program week |
| `{{ checkin_url }}` | Direct link to check-in form |
| `{{ deliverables_url }}` | Direct link to deliverables page |
| `{{ program_title }}` | From Config sheet |
| `{{ base_url }}` | App base URL |

**Built-in templates**:

| Slug | Subject | When Used |
|------|---------|-----------|
| `welcome` | `Welcome to {{ program_title }}` | Auto-sent on successful claim |
| `weekly-reminder` | `Week {{ week_number }} check-in is open` | Manual send each week |
| `missing-checkin` | `Don't forget your Week {{ week_number }} check-in` | Send to interns who haven't submitted |
| `custom` | Admin-entered subject | Free-form admin message |

### 11.3 Send Flow

```
Admin → /admin/email
    │
    ├── Select audience
    ├── Select or write template
    ├── Preview rendered email (one sample recipient)
    ├── Confirm send
    │
    ▼
App iterates recipients, sends via ForwardEmail REST API
    │
    ▼
Each send logged to Email_Log sheet
    │
    ▼
Admin sees summary: N sent, M failed
```

### 11.4 Constraints

- Admin-only — sponsors and interns cannot trigger bulk email
- Cap: no more than 50 emails per single send action
- All sends logged to `Email_Log` for audit
- `welcome` email sent automatically on successful claim

---

## 12. API Routes

### 12.1 Public (no auth)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Sign-in page |
| GET | `/program` | Public dashboard: tracks + interns + deliverables |
| GET | `/health` | Health check |

### 12.2 Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/request-link` | Send magic link |
| GET | `/auth/verify` | Validate token, create session, redirect by role |
| POST | `/auth/logout` | Clear session |
| GET | `/claim` | Claim form (intern_id entry) |
| POST | `/claim` | Process claim, bind email |

### 12.3 Intern

| Method | Path | Description |
|--------|------|-------------|
| GET | `/home` | Dashboard: track info, check-in status, deliverable count |
| GET | `/onboarding` | Onboarding form |
| POST | `/onboarding` | Submit onboarding |
| GET | `/checkin` | Current week check-in form (or past submissions if already done) |
| POST | `/checkin` | Submit check-in |
| GET | `/deliverables` | View own deliverables + submission form |
| POST | `/deliverables` | Submit new deliverable |
| GET | `/me` | Profile view/edit |
| POST | `/me` | Update profile |

### 12.4 Sponsor

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sponsor` | Track overview: interns, check-in status, deliverables |
| GET | `/sponsor/intern/{intern_id}` | Individual intern detail |
| GET | `/sponsor/feedback` | Feedback form |
| POST | `/sponsor/feedback` | Submit mentor feedback |

### 12.5 Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin` | All interns, program-wide progress overview |
| GET | `/admin/intern/{intern_id}` | Individual intern detail |
| GET | `/admin/attendance` | Attendance log + entry form |
| POST | `/admin/attendance` | Log attendance |
| GET | `/admin/email` | Email composer |
| POST | `/admin/email/preview` | Render preview for one sample recipient |
| POST | `/admin/email/send` | Send emails, log results |

---

## 13. Public Dashboard (`/program`)

No auth required. Shows:

- Program header: title, dates, track count, active intern count
- Each active track: name, sponsor name, description
- Per track: list of interns (preferred name or first name) and their submitted deliverables (title + URL)
- Interns without claimed accounts shown as "TBD"
- Deliverables without a URL shown as text only

**Not exposed publicly**: check-in content, mentor feedback, attendance, ratings, email addresses.

---

## 14. Caching

In-memory cache (single process). Invalidate on writes.

| Data | TTL | Invalidate On |
|------|-----|---------------|
| Config values | 5 min | — |
| Tracks list | 10 min | — |
| Roster by email | 2 min | claim, onboarding, profile update |
| Roster by intern_id | 2 min | same |
| Check-ins for intern | 2 min | check-in submit |
| Deliverables for intern | 2 min | deliverable submit |
| All interns (admin/public view) | 2 min | any roster write |

---

## 15. UI — Visual Design

### 15.1 Theme

The app matches the **Cyber Defenders Program** visual identity used on `cyberdefendersprogram.com`. This means:

**CSS Framework**: Bulma (loaded from CDN, same version as the main site)

**Fonts**:
- Headings: `Roboto Mono` (Google Fonts) — same as `.is-hackathon-h2` on the main site
- Body: `Lato` (Google Fonts) — same as the main site body font

**Color palette** (from `main.css`):

| Name | Hex | Use |
|------|-----|-----|
| CDP Navy | `#062F49` | Page headers, navbar background |
| CDP Blue | `#5893BC` | Section headings, card borders, accent |
| CDP Salmon | `#FA7C91` | CTA buttons, card top/left borders, highlights |
| CDP Light | `#EFF3F4` | Alternating section backgrounds |
| CDP Footnote | `#F1F3FA` | Apply-section and footer backgrounds |

**Logo**: The CDP logo (`logo.png`) and text lockup (`logo-title.png`) are served as static assets copied from the www-homepage repo into `app/static/images/`. The navbar uses the same logo shown on `cyberdefendersprogram.com`.

### 15.2 Layout and Components

**Navbar** (all authenticated pages):
- Navy (`#062F49`) background
- CDP logo left-aligned
- Nav links right: role-appropriate (Home / Track / Profile / Logout)
- Responsive burger menu on mobile

**Cards**: Bulma `.card` with:
- `border-top: 4px solid #5893BC` (detail cards)
- `border-left: 4px solid #FA7C91` (track/highlight cards)
- `.heading` labels in `#5893BC` / Roboto Mono

**Section backgrounds**: Alternate between `#EFF3F4` and `#fff`, matching intern.html pattern

**Buttons**:
- Primary CTA: Bulma `.button.is-primary` → renders as `#FA7C91` (salmon) per site's Bulma overrides
- Secondary: Bulma `.button.is-light`
- Destructive / admin: Bulma `.button.is-danger`

**Flash messages**: Bulma `.notification` with `.is-success`, `.is-warning`, `.is-danger`

**Forms**: Bulma `.field` / `.control` / `.input` / `.textarea` / `.select` components

### 15.3 Screens by Role

| Path | Role | Screen |
|------|------|--------|
| `/` | public | Sign-in: CDP-branded hero, email input |
| `/program` | public | Track + intern + deliverable dashboard |
| `/claim` | unauthenticated | intern_id entry form |
| `/onboarding` | intern | Profile completion form |
| `/home` | intern | Dashboard: track card, week status, deliverable list |
| `/checkin` | intern | Weekly check-in form |
| `/deliverables` | intern | Deliverable list + submit form |
| `/me` | intern | Profile view/edit |
| `/sponsor` | sponsor | Track overview table |
| `/sponsor/intern/{id}` | sponsor | Intern detail: check-ins, deliverables, feedback form |
| `/admin` | admin | All interns table with week status indicators |
| `/admin/intern/{id}` | admin | Full intern detail |
| `/admin/attendance` | admin | Attendance sheet-style form |
| `/admin/email` | admin | Audience picker + template selector + preview + send |

### 15.4 Static Assets

Assets to copy from www-homepage at build time (or commit into `app/static/`):

| File | Source | Use |
|------|--------|-----|
| `logo.png` | `assets/images/logo.png` | Navbar logo |
| `logo-title.png` | `assets/images/logo-title.png` | Sign-in hero |
| `GotMalware.png` | `assets/images/program/GotMalware.png` | Public dashboard section image |
| `code_stockphoto.jpg` | `assets/images/program/code_stockphoto.jpg` | Sign-in hero background |

---

## 16. Logging

Structured JSON to stdout.

| Event | Level | Fields |
|-------|-------|--------|
| `magic_link_sent` | INFO | email |
| `magic_link_rate_limited` | WARN | email, count |
| `claim_success` | INFO | intern_id, email |
| `login_success` | INFO | intern_id, role |
| `checkin_submitted` | INFO | intern_id, week_number |
| `deliverable_submitted` | INFO | intern_id, week_number |
| `email_sent` | INFO | sender, template, recipient_count |
| `email_failed` | ERROR | recipient, error |
| `sheets_error` | ERROR | operation, error |

---

## 17. Health Check

`GET /health`

```json
{
  "status": "ok",
  "checks": {
    "sqlite": true,
    "sheets": true
  },
  "version": "1.0.0"
}
```

Returns `200` if healthy, `503` if degraded.

---

## 18. Deferred (v2)

- Discord channel sync (activity signals, standup ingestion)
- Automated scheduled reminders (cron-triggered, not manual)
- Intern-facing deliverable comments from sponsor
- PDF export of intern progress report
- Bulk attendance import from CSV

---

## 19. Acceptance Criteria

- [ ] 25 interns can log in simultaneously without rate-limit errors
- [ ] Magic link → claim → onboarding works end-to-end for interns
- [ ] Sponsors log in and see only their own track's interns
- [ ] Admins see all interns and can log attendance and send email
- [ ] Email reminders render template variables correctly and log to `Email_Log` sheet
- [ ] Public `/program` shows tracks + interns + deliverable links without auth
- [ ] Track config changes in Sheets reflected within 10 minutes (cache TTL)
- [ ] UI matches CDP brand: navy navbar, Roboto Mono headings, salmon CTAs, Bulma cards
- [ ] CDP logo appears in navbar and sign-in page
- [ ] Push to `main` deploys within 5 minutes
- [ ] Monthly infrastructure cost delta: $0 (shared droplet)

---

**End of Specification**
