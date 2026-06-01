# Tasks Feature — Full Design

## Design Principles

- Google Sheets is the single source of truth (existing pattern)
- In-memory cache handles all rate limiting for reads (existing `app/services/cache.py`)
- SQLite stays auth-only (magic_tokens, rate_limits, intern_cache) — no new tables
- Tasks are a unified status layer over existing features, not a new data silo
- Same API endpoints serve both web and Discord bot

---

## Task Types

| Type | Created by | Example |
|---|---|---|
| `system` | App automatically | "Submit Week 3 check-in" |
| `assigned` | Admin or mentor | "Research CVE-2024-1234 for track" |
| `self` | Intern themselves | "Read MITRE ATT&CK framework" |

Template tasks are rows in `Task_Templates` sheet. App fans them out to individual
interns on `program_start_date` — no separate type needed at runtime.

---

## Task Schema

```
task_id          UUID (stable across web + Discord)
title            string
description      text (markdown, optional — renders in Discord embeds)
task_type        system | assigned | self
assigned_to      intern_id | "track:track-1" | "all"
assigned_by      intern_id | "system"
track_id         string (FK → Tracks, optional)
week_number      integer (which week task belongs to; null = anytime)
due_week         integer (when it's due)
status           todo | done | skipped
priority         normal | high
linked_feature   checkin | deliverable | onboarding | blank
source           web | discord | system
created_at       ISO timestamp
completed_at     ISO timestamp
```

`linked_feature` is the key field — when an intern submits a check-in, the app
auto-completes the matching `linked_feature=checkin` task for that week.
No double-entry; submitting the check-in IS the task completion.

```python
# When intern submits check-in:
complete_linked_tasks(intern_id, week_number, linked_feature="checkin")

# When deliverable submitted:
complete_linked_tasks(intern_id, week_number, linked_feature="deliverable")

# When onboarding completed:
complete_linked_tasks(intern_id, linked_feature="onboarding")
```

---

## The 6-Week Task Timeline

System auto-generates these for every intern on `program_start_date`:

```
WEEK 1 — Onboarding
  [system]   Complete your profile (linked: onboarding)
  [system]   Submit Week 1 check-in (linked: checkin, due_week: 1)
  [system]   Introduce yourself in #general (Discord-native)
  [system]   Join your track channel on Discord
  [template] Read track briefing doc (mentor sets URL)

WEEK 2
  [system]   Submit Week 2 check-in (linked: checkin)
  [system]   Post your first deliverable idea in Discord
  [template] Schedule 1:1 with mentor

WEEK 3 — Mid-point
  [system]   Submit Week 3 check-in (linked: checkin)
  [system]   Submit mid-program deliverable (linked: deliverable)
  [system]   Complete mid-program self-assessment

WEEK 4
  [system]   Submit Week 4 check-in (linked: checkin)
  [template] Peer review: review another intern's Week 3 deliverable

WEEK 5
  [system]   Submit Week 5 check-in (linked: checkin)
  [system]   Draft final deliverable outline (linked: deliverable)
  [template] Present progress update to mentor

WEEK 6 — Demo Day
  [system]   Submit Week 6 check-in (linked: checkin)
  [system]   Submit final deliverable (linked: deliverable)
  [system]   Complete program exit survey
  [system]   Post demo-day reflection in Discord
```

---

## Role Workflows

### Intern — week by week

```
Monday    Bot DMs: "Week N starts. You have 3 tasks due this week."
          /tasks → see the list

Mid-week  Submits check-in on web → "Submit check-in" task auto-completes
          Bot confirms: "✅ Week N check-in logged. 2 tasks remaining."

Anytime   /task add "Review nmap scan results" → self-task created
          /tasks → open tasks with done count

Sunday    Overdue reminder DM if anything still open
```

### Mentor

```
Week start  /tasks track → all open tasks across their interns
            Web /tasks shows track-level board

Assign      /task assign @intern "Analyze packet capture from Tuesday"
            OR web: create task → pick intern from dropdown

Review      Deliverable submitted → linked task auto-closes
            Bot pings mentor channel: "2 interns missing Week N check-in"

Feedback    After reviewing a deliverable, feedback form auto-creates a
            follow-up task for the intern: "Address feedback on Week 3 report"
```

### Admin

```
Pre-program  Seed Task_Templates sheet tab (once)
             make seed-tasks fans them out to all interns

Weekly       /tasks overdue → who's behind across all tracks
             Web dashboard: week × track completion heat map
             One-click "send reminder" → email + Discord DM

Ad-hoc       Assign to individual, track, or all interns at once
```

### Sponsor

```
Read-only.
/tasks track → track's open tasks and completion status
Web /sponsor shows task completion % alongside check-in status
```

---

## Discord Identity Linking

Discord user IDs are stable snowflakes — use these as the join key, never username.

### Two new Roster columns

```
discord_id        string   set once on /link; never changes
discord_notify    boolean  true (default) | false — set via /notify off
```

Stored in Sheets → survives container restarts. In-memory cache makes lookups fast.

### Linking flow

```
User runs /link in Discord
        │
Bot: "What's your program email?"
        │
FastAPI sends magic link to that email (existing flow)
        │
User clicks link in browser
        │
/auth/discord-link?token=...&discord_id=...
        ├── validates token (proves email ownership)
        ├── writes discord_id to Roster sheet
        └── invalidates roster cache → next bot request resolves correctly
```

### Lookup at runtime

```python
# Bot handler resolves discord_id → InternEntry via cached roster
intern = get_roster_by_discord_id(discord_id)  # in-memory cache hit: ~1ms
if not intern:
    return "Run /link first to connect your Discord to your program account."
```

Cold cache miss → Sheets read (~300ms) → well within Discord's 3s interaction timeout.

### Handling OpenClaw workspace updates

- Discord IDs never change — links stay valid through renames and role changes
- On `member_remove`: clear `discord_id` from Roster (or leave for audit)
- On `member_add`: bot DMs new member to run `/link`
- If OpenClaw exposes a member→email mapping, admin can pre-populate `discord_id`
  in the Roster sheet to skip the user-action step entirely

---

## Discord Commands

### Intern

```
/tasks                    → open tasks this week, by priority
/tasks all                → full list with status badges
/tasks week <n>           → tasks for a specific week
/task done <id>           → mark complete
/task skip <id> <reason>  → mark skipped with reason
/task add <title>         → create self-task
/task view <id>           → full details + description
/notify off               → pause non-critical DMs
```

### Mentor / admin extras

```
/tasks track              → all open tasks for your track's interns
/tasks overdue            → overdue across track (or all, for admin)
/task assign @user <title> [week:<n>] [priority:high]
/task broadcast <title>   → assign to all interns in your track
/tasks summary            → "Week 4: 18/25 check-ins, 12/25 deliverables"
```

### Bot response format

```
📋 Your tasks — Week 4

🔴 HIGH
  #t42  Submit mid-program deliverable (due this week)

🟡 NORMAL
  #t38  Submit Week 4 check-in ✅ done
  #t39  Schedule 1:1 with mentor
  #t41  Peer review: @alexsmith deliverable

/task done <id>  |  /tasks all
```

---

## Notification Design

```
IMMEDIATE (bot DM)
  ├── New high-priority task assigned to you
  ├── Mentor leaves feedback on your deliverable
  └── Task overdue (day after due_week ends)

WEEKLY DIGEST (Monday 9am, bot DM)
  ├── Tasks due this week
  ├── Carry-overs from last week still open
  └── "Your track: N/5 check-ins submitted last week"

CHANNEL PINGS (mentor/admin channels only — never ping interns publicly)
  ├── @mentor: 2 interns missing Week N check-in
  └── @admin: Week N summary — X% completion across all tracks
```

---

## Architecture

```
Google Sheets (source of truth)
  ├── Roster  (+ discord_id, discord_notify columns)
  ├── Tasks
  └── Task_Templates

In-memory cache  (existing app/services/cache.py)
  ├── roster by id / email / discord_id   TTL: 2 min
  ├── tasks by intern_id                  TTL: 2 min
  └── tasks by track_id                  TTL: 2 min

SQLite  (auth only — unchanged)
  ├── magic_tokens
  ├── rate_limits
  └── intern_cache  (stale-serving when Sheets is unavailable)

Bot  (OpenClaw — HTTP client to FastAPI)
  └── authenticates with BOT_API_KEY bearer token (new env var)
```

No new SQLite tables. No new infrastructure.

### When to revisit SQLite for tasks

| Trigger | Why SQLite then |
|---|---|
| 200+ users | In-memory cache pressure; Sheets rate limits become real |
| Complex queries | JOIN across tasks + roster + tracks |
| Concurrent writes | Task status races need transactions |
| Audit log | Immutable append-only log |

None apply to a 6-week, 25-intern program.

---

## Google Sheets Changes

### Roster — two new columns

| Column | Type | Source |
|---|---|---|
| `discord_id` | string | Set by `/link` flow; blank until linked |
| `discord_notify` | boolean | `true` default; set to `false` via `/notify off` |

### New tab: `Tasks`

| Column | Type | Description |
|---|---|---|
| `task_id` | string | UUID |
| `title` | string | |
| `description` | string | Markdown, optional |
| `task_type` | string | `system`, `assigned`, `self` |
| `assigned_to` | string | `intern_id`, `track:track-1`, `all` |
| `assigned_by` | string | `intern_id` or `system` |
| `track_id` | string | FK → Tracks |
| `week_number` | integer | |
| `due_week` | integer | |
| `status` | string | `todo`, `done`, `skipped` |
| `priority` | string | `normal`, `high` |
| `linked_feature` | string | `checkin`, `deliverable`, `onboarding`, blank |
| `source` | string | `web`, `discord`, `system` |
| `created_at` | ISO timestamp | |
| `completed_at` | ISO timestamp | |

### New tab: `Task_Templates`

Admin edits once. App fans out on `program_start_date` (or `make seed-tasks`).

| Column | Type | Description |
|---|---|---|
| `template_id` | string | |
| `title` | string | |
| `description` | string | |
| `task_type` | string | |
| `assigned_to` | string | `all`, `role:intern`, `track:track-1` |
| `week_number` | integer | |
| `due_week` | integer | |
| `priority` | string | |
| `linked_feature` | string | |

---

## API Endpoints

```
GET   /api/tasks                → my tasks (role-filtered; ?week=N optional)
POST  /api/tasks                → create task
PATCH /api/tasks/{task_id}      → update status / fields
GET   /api/tasks/team           → mentor/sponsor: track's open tasks
GET   /api/tasks/overdue        → admin/mentor: overdue tasks
GET   /api/tasks/summary        → admin: week × track completion matrix

POST  /auth/discord-link        → complete Discord identity linking
```

Bot uses `BOT_API_KEY` bearer token. Web uses existing session cookie.
Same business logic, same endpoints.

---

## Web Pages

| Path | Role | View |
|---|---|---|
| `/tasks` | intern | This week's tasks + quick-add |
| `/tasks/all` | intern | Full history by week |
| `/tasks/track` | mentor/sponsor | Track-wide task board |
| `/tasks/admin` | admin | All-intern matrix: week × completion % |

---

## Build Order

### Phase 1 — Foundation (web only)

1. Add `discord_id` and `discord_notify` to Roster sheet + `SheetsClient`
2. Add `Task_Templates` and `Tasks` sheet tabs
3. `SheetsClient` methods: `get_tasks`, `create_task`, `update_task_status`
4. Template fan-out script (`make seed-tasks`)
5. Auto-complete hook in check-in + deliverable submit handlers
6. `/api/tasks` CRUD endpoints with role filtering
7. `/tasks` web pages per role

### Phase 2 — Discord read + link

1. `get_roster_by_discord_id` cache method
2. `/link` slash command + `/auth/discord-link` endpoint
3. `/tasks`, `/task done`, `/task add` Discord commands
4. Weekly digest DM (Monday 9am)

### Phase 3 — Discord write + notifications

1. `/task assign`, `/task broadcast` commands
2. Overdue DM reminders (Sunday evening)
3. Mentor channel summaries on check-in deadline
4. `/notify off` preference via `discord_notify` Roster column
