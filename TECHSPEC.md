# Auto Job Apply — Technical Specification

**Version:** 0.1 (Draft)
**Date:** 2026-05-10
**Owner:** Nitin
**Mode:** Fully local — UI, backend, browser automation, scheduler, and LLM calls all run on the user's machine.

---

## 1. Goals

Build a single-user, local-first system that:

1. **Discovers jobs via APIs / MCP connectors only** — no browser automation for search. Sources: Indeed MCP, Dice MCP, Greenhouse public boards API, Lever public API, LinkedIn Jobs (via official API where licensed, otherwise an opt-in HTTP scraper kept off by default).
2. Scores each job against the user's resume, skills, and preferences using the Claude API.
3. Generates tailored cover letters and screening answers per job.
4. **Applies via Playwright browser automation** — application submission is the *only* place a real browser is used.
5. Tracks every job's lifecycle (seen → scored → approved → applied → outcome) in a local database, deduplicated to prevent re-applying.
6. Exposes a local web UI for editing the profile, reviewing the queue, monitoring runs, and inspecting failures.
7. Emails a daily digest with an Excel attachment summarizing searched / applied / failed jobs.

### Hard architectural rule

**Search = API/MCP. Apply = Playwright. They never swap.** This keeps search fast, parallel, and unbannable; keeps apply realistic (forms genuinely require a browser); and gives a clean failure boundary — search failures are HTTP errors, apply failures are screenshots.

### Non-goals

- Multi-user / SaaS hosting.
- Replacing the user's judgment on senior-level or high-stakes applications (those flow through the approval queue).
- Bypassing CAPTCHAs, MFA, or anti-bot challenges through paid services.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Local Machine                              │
│                                                                   │
│  ┌──────────────┐      ┌────────────────┐     ┌───────────────┐  │
│  │  Web UI      │─────▶│  FastAPI       │────▶│   SQLite      │  │
│  │  (HTMX +     │      │  Backend       │     │   (jobs.db)   │  │
│  │   Tailwind)  │◀─────│                │◀────│               │  │
│  └──────────────┘ SSE  └───┬────────────┘     └───────────────┘  │
│       :8000                │                                      │
│                            │ in-process                           │
│                            ▼                                      │
│                  ┌───────────────────┐                            │
│                  │  APScheduler      │                            │
│                  │  (search/score/   │                            │
│                  │   apply workers)  │                            │
│                  └─┬───────┬───────┬─┘                            │
│                    │       │       │                              │
│         ┌──────────▼──┐ ┌──▼────┐ ┌▼────────────┐                 │
│         │ Sources     │ │ LLM   │ │ Playwright  │                 │
│         │  scrapers   │ │ Claude│ │  workers    │                 │
│         │ (LinkedIn,  │ │  API  │ │ (per-source │                 │
│         │  Indeed,    │ │ SDK + │ │  handlers)  │                 │
│         │  Greenhouse)│ │ cache │ │             │                 │
│         └─────────────┘ └───────┘ └─────────────┘                 │
│                                          │                        │
│                                          ▼                        │
│                              ┌────────────────────┐               │
│                              │  ./browser_state/  │               │
│                              │   per-source       │               │
│                              │   persistent ctx   │               │
│                              └────────────────────┘               │
└──────────────────────────────────────────────────────────────────┘
```

Everything binds to `127.0.0.1`. No inbound network exposure.

---

## 3. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Playwright + Anthropic SDK + FastAPI all first-class. |
| Web framework | FastAPI | Async, simple, great for both REST + SSE. |
| Frontend | Server-rendered Jinja + HTMX + Tailwind | No SPA build step; fast iteration; one process. |
| DB | SQLite (via SQLAlchemy 2.x) | Single file, zero ops, good enough for one user. |
| Scheduler | APScheduler (in-process, SQLAlchemy jobstore) | No Celery/Redis needed. |
| Browser automation | Playwright (Python) with persistent contexts | Stable, scriptable, fast. |
| LLM | **Claude Code** (CLI in headless mode, or Claude Agent SDK) — uses the user's existing Claude subscription, no separate API key | Reuses the user's logged-in Claude Code auth; no `ANTHROPIC_API_KEY` to manage. |
| Auth (UI) | None (localhost-only) | Single-user, local. Optional: simple shared-secret cookie if exposed over Tailscale. |
| Process manager | `uvicorn` + `systemd --user` unit (or `supervisord`) | Survives reboots. |
| Config | `.env` (secrets) + `profile/preferences.yaml` (user prefs) | Secrets never in DB or git. |

---

## 4. Repository Layout

```
auto-job-apply/
├── README.md
├── TECHSPEC.md                 # this file
├── pyproject.toml
├── .env.example
├── .gitignore                  # MUST include .env, browser_state/, *.db, profile/resume.pdf
│
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # pydantic-settings; loads .env
│   ├── db.py                   # SQLAlchemy engine + session
│   ├── models.py               # ORM models
│   ├── schemas.py              # pydantic request/response models
│   │
│   ├── api/                    # REST endpoints
│   │   ├── jobs.py
│   │   ├── profile.py
│   │   ├── runs.py
│   │   └── events.py           # SSE stream
│   │
│   ├── ui/                     # HTMX views
│   │   ├── routes.py
│   │   └── templates/
│   │       ├── base.html
│   │       ├── dashboard.html
│   │       ├── queue.html
│   │       ├── job_detail.html
│   │       ├── profile.html
│   │       └── runs.html
│   │
│   ├── llm/
│   │   ├── client.py           # Anthropic SDK wrapper, prompt cache helpers
│   │   ├── scoring.py          # job-fit scoring
│   │   ├── cover_letter.py     # tailored cover letter generation
│   │   └── screening.py        # answers screening questions from preferences
│   │
│   ├── sources/                # API/MCP only — never browser
│   │   ├── base.py             # SourceProtocol: search() -> list[JobPosting]
│   │   ├── mcp_client.py       # talks to scripts/mcp_host.py
│   │   ├── indeed.py           # via MCP
│   │   ├── dice.py             # via MCP
│   │   ├── greenhouse.py       # HTTP boards-api.greenhouse.io
│   │   ├── lever.py            # HTTP api.lever.co
│   │   ├── linkedin.py         # HTTP, opt-in, off by default
│   │   └── rss.py              # generic RSS/Atom/JSON-Feed adapter
│   │
│   ├── apply/                  # one handler per submission target
│   │   ├── base.py             # ApplyHandler: apply(job, profile) -> ApplyResult
│   │   ├── linkedin_easy.py
│   │   ├── greenhouse.py
│   │   ├── lever.py
│   │   ├── workday.py
│   │   └── generic.py          # best-effort form filler
│   │
│   ├── browser/
│   │   ├── context.py          # persistent context per source
│   │   └── helpers.py          # human-like delays, scroll, screenshot-on-fail
│   │
│   ├── scheduler/
│   │   ├── runner.py           # APScheduler init + jobs
│   │   ├── search_job.py       # periodic search across enabled sources
│   │   ├── score_job.py        # scores `new` rows
│   │   └── apply_job.py        # picks `approved` rows and submits
│   │
│   └── services/
│       ├── dedupe.py           # job_hash logic
│       ├── notify.py           # Gmail / webhook digest
│       ├── export.py           # daily/weekly Excel exports
│       └── events.py           # in-memory pub/sub for SSE
│
├── profile/
│   ├── resume.md               # source of truth, markdown
│   ├── resume.pdf              # rendered for upload (gitignored)
│   ├── skills.md
│   ├── preferences.yaml
│   └── answers.yaml            # canonical screening answers
│
├── browser_state/              # gitignored; one dir per source
│   ├── linkedin/
│   ├── indeed/
│   └── ...
│
├── data/
│   └── jobs.db                 # SQLite (gitignored)
│
├── logs/
│   ├── runs/                   # per-run markdown summaries
│   └── screenshots/            # failure screenshots, named by job_id+timestamp
│
└── tests/
    ├── unit/
    └── integration/            # mocked Playwright + recorded LLM responses
```

---

## 5. Profile Files

### 5.1 `profile/preferences.yaml`

```yaml
identity:
  full_name: "Nitin Jha"
  email: "jhanitin906@gmail.com"
  phone: "+91-XXXXXXXXXX"
  location_current: "Bengaluru, India"
  work_authorization: "India citizen, no sponsorship needed for India roles"
  linkedin_url: "https://linkedin.com/in/..."
  github_url: "https://github.com/nitin611"

targeting:
  titles:
    - "Software Engineer"
    - "Backend Engineer"
    - "Full Stack Engineer"
  seniority: ["mid", "senior"]
  experience_years_min: 2
  experience_years_max: 8
  locations:
    - "Bengaluru"
    - "Remote (India)"
  work_modes: ["remote", "hybrid"]    # subset of [remote, hybrid, onsite]
  ctc_min_inr: 1800000                 # annual, INR
  ctc_target_inr: 3000000

filters:
  must_have_keywords: ["python", "backend"]
  nice_to_have_keywords: ["aws", "kubernetes", "react"]
  blacklist_keywords: ["unpaid", "commission only", "java only"]
  blacklist_companies: ["AcmeCorp"]
  exclude_if_posted_more_than_days: 21

scoring:
  min_score_to_qualify: 7              # 0-10
  auto_apply_threshold: null           # null = always require manual approval
                                       # or e.g. 9 = auto-apply if score >= 9

limits:
  max_applications_per_day_total: 15
  max_applications_per_source_per_day:
    linkedin: 8
    indeed: 5
    greenhouse: 5
  search_runs_per_day: 4

sources:
  indeed:
    enabled: true                    # via MCP
  dice:
    enabled: true                    # via MCP
  greenhouse:
    enabled: true                    # public HTTP API; provide company slugs
    company_slugs: ["airbnb", "stripe", "figma"]
  lever:
    enabled: true                    # public HTTP API
    company_slugs: ["netflix", "shopify"]
  linkedin:
    enabled: true
    mode: "apify"                    # apify | rapidapi
    apify:
      actor: "fantastic-jobs/advanced-linkedin-job-search-api"
      token_env: "APIFY_TOKEN"
      max_results_per_run: 100
      posted_within_hours: 168       # last 7 days
    rapidapi:
      host: "linkedin-job-search-api.p.rapidapi.com"
      key_env: "RAPIDAPI_KEY"
      endpoint: "/active-jb-7d"
  rss:
    enabled: false
    feeds: []
```

### 5.2 `profile/answers.yaml`

```yaml
# Canonical answers for common screening questions.
# Keys are matched fuzzily by the LLM; values used verbatim.
work_authorization_india: "Yes"
work_authorization_us: "No"
sponsorship_required: "No"
years_of_experience: 4
notice_period_days: 60
current_ctc_inr: 1800000
expected_ctc_inr: 3000000
willing_to_relocate: "Open for Bengaluru / Remote"
preferred_start_date: "Within 60 days"
gender: "Prefer not to say"
ethnicity: "Prefer not to say"
disability: "No"
veteran: "No"
```

### 5.3 `profile/resume.md` and `profile/skills.md`

Free-form markdown. `resume.md` is the canonical version; `resume.pdf` is rendered from it (script: `scripts/render_resume.py` using e.g. pandoc) and used for uploads.

---

## 6. Data Model

SQLAlchemy 2.x. All timestamps UTC.

### 6.1 `jobs`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| job_hash | TEXT UNIQUE | `sha1(source + canonical_url + company + title)` |
| source | TEXT | `linkedin`, `indeed`, `dice`, `greenhouse`, `lever`, `manual` |
| source_job_id | TEXT NULL | source's native id when available |
| url | TEXT | |
| canonical_url | TEXT | tracking-stripped |
| title | TEXT | |
| company | TEXT | |
| location | TEXT | |
| work_mode | TEXT | `remote`/`hybrid`/`onsite`/`unknown` |
| ctc_min, ctc_max | INTEGER NULL | INR |
| description_md | TEXT | markdown-converted JD |
| posted_at | TIMESTAMP NULL | |
| discovered_at | TIMESTAMP | |
| status | TEXT | `new` → `scored` → `qualified` / `skipped` → `approved` → `applying` → `applied` / `failed` |
| score | REAL NULL | 0–10 |
| score_rationale | TEXT NULL | |
| skip_reason | TEXT NULL | |
| apply_handler | TEXT NULL | which `ApplyHandler` to use |
| raw_payload | JSON | original scraper output |

Indexes: `(status)`, `(source, discovered_at)`, `(score DESC)`.

### 6.2 `applications`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| job_id | FK → jobs.id | |
| started_at | TIMESTAMP | |
| finished_at | TIMESTAMP NULL | |
| outcome | TEXT | `submitted`, `failed`, `needs_human` |
| failure_reason | TEXT NULL | |
| screenshot_path | TEXT NULL | |
| cover_letter_md | TEXT NULL | what we sent |
| screening_answers_json | JSON NULL | what we answered |
| confirmation_text | TEXT NULL | text scraped from confirmation page |

### 6.3 `runs`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| kind | TEXT | `search`, `score`, `apply` |
| started_at, finished_at | TIMESTAMP | |
| status | TEXT | `running`, `success`, `error` |
| stats_json | JSON | `{"discovered": 23, "new": 5, ...}` |
| log_path | TEXT | path under `logs/runs/` |

### 6.4 `profile_state`

Single-row table caching parsed `preferences.yaml`, `resume.md`, content hash, and last-modified timestamp — used to invalidate the LLM prompt cache key when the user edits.

---

## 7. Job Lifecycle (state machine)

```
        discovered
            │
            ▼
        ┌───────┐  blacklist/dup  ┌─────────┐
        │  new  │────────────────▶│ skipped │
        └───┬───┘                 └─────────┘
            │ score()
            ▼
        ┌────────┐  score < threshold
        │ scored │──────────────────────────────▶ skipped
        └───┬────┘
            │ score >= threshold
            ▼
       ┌───────────┐ user reject       ┌─────────┐
       │ qualified │──────────────────▶│ skipped │
       └─────┬─────┘                   └─────────┘
             │ user approve  OR  auto_apply_threshold met
             ▼
        ┌──────────┐
        │ approved │
        └─────┬────┘
              │ apply worker picks up
              ▼
        ┌──────────┐  Playwright handler
        │ applying │
        └─────┬────┘
        ┌─────┴──────┐
        ▼            ▼
   ┌─────────┐  ┌────────┐
   │ applied │  │ failed │ ─── retried up to N times if transient
   └─────────┘  └────────┘
```

Transitions are the only writes to `status`; each transition emits an event for the SSE stream.

---

## 8. Component Specs

### 8.1 Source clients (`app/sources/`) — API/MCP only, no browser

Each implements:

```python
class SourceProtocol(Protocol):
    name: str
    transport: Literal["http", "mcp"]
    async def search(self, prefs: Preferences) -> list[JobPosting]: ...
```

| Source | Transport | Endpoint / tool | Notes |
|---|---|---|---|
| **Indeed** | MCP | `mcp__claude_ai_Indeed__search_jobs`, `..._get_job_details`, `..._get_company_data` | Reached via a local MCP host process the backend talks to over stdio/HTTP. |
| **Dice** | MCP | `mcp__claude_ai_Dice__search_jobs` | Same MCP host. |
| **Greenhouse** | HTTP | `GET https://boards-api.greenhouse.io/v1/boards/<company>/jobs?content=true` | Pure HTTP. Company slugs from `preferences.yaml`. |
| **Lever** | HTTP | `GET https://api.lever.co/v0/postings/<company>?mode=json` | Same. |
| **LinkedIn** | HTTP via 3rd-party | **Apify** actor (default) or **RapidAPI** provider (fallback) | LinkedIn's official Jobs API is gated behind the Talent Solutions Partner Program ($700+/mo, recruiter-side only) so we use a 3rd-party search API. Mode selected in `preferences.yaml`. **No Playwright fallback for search.** |
| **Custom RSS / boards** | HTTP | user-supplied feeds | Generic RSS/Atom or JSON Feed adapter for niche boards. |

The MCP host (`scripts/mcp_host.py`) is a thin Python process that loads the user's MCP server configs (same JSON the Claude Code CLI uses) and exposes a local JSON-RPC endpoint. The backend's source clients call it instead of speaking MCP directly — keeps the FastAPI process clean and lets MCP servers crash/reconnect independently.

All search operations are **rate-limited and parallelized** at the API layer: each source has its own token bucket. No persistent browser state, no cookies, no anti-bot risk.

Outputs are normalized into `JobPosting` (pydantic), then upserted via `dedupe.upsert_job()`.

#### 8.1.1 LinkedIn source — modes

`app/sources/linkedin.py` supports two interchangeable modes selected from `preferences.yaml`:

**Mode `apify` (default).** Uses Apify's hosted LinkedIn job-search actor (e.g. `fantastic-jobs/advanced-linkedin-job-search-api`). Async pattern:

1. `POST https://api.apify.com/v2/acts/<actor>/runs?token=$APIFY_TOKEN` with input JSON built from preferences (titles, locations, work_modes, posted_within, experience_levels). Persist `run_id`.
2. On the next scheduler tick, `GET /v2/actor-runs/<run_id>` until status is `SUCCEEDED`, then `GET /v2/actor-runs/<run_id>/dataset/items` for the rows.
3. Normalize to `JobPosting`. Real-time scrape → fresher results (good for first-day applications). Cost: roughly $0.50–$2 per 1000 jobs.

**Mode `rapidapi` (fallback).** Single REST call, cached results from the provider's side. Synchronous:

1. `GET https://<host>/active-jb-7d?title_filter=...&location_filter=...&remote=true` with `X-RapidAPI-Key: $RAPIDAPI_KEY` and `X-RapidAPI-Host: <host>`.
2. Provider returns a paginated JSON list. Normalize to `JobPosting`.
3. Cheaper at low volume; results are hours-stale.

Both modes accept the same normalized filter set and emit the same `JobPosting` shape, so swapping is a one-line config change. If the active mode errors, the search run for LinkedIn is recorded as failed and continues with the other sources — there is no Playwright fallback.

### 8.2 Dedupe

`job_hash = sha1(f"{source}|{canonical_url}|{company.lower()}|{title.lower()}")`.

`canonical_url` strips: `utm_*`, `gh_src`, `trk`, fragments. SQLite UNIQUE constraint on `job_hash` makes the upsert idempotent. Cross-source dupes (same job posted on LinkedIn and the company's Greenhouse) are collapsed by a secondary fuzzy check on `(company, title, posted_at within 7 days)` — flagged but kept separate so the apply path still uses the better source.

### 8.3 LLM layer (`app/llm/`) — driven by Claude Code, no API key

The backend invokes the user's locally-installed Claude Code instead of calling the Anthropic API directly. This means no `ANTHROPIC_API_KEY` in `.env` and no separate billing — the user's existing Claude Pro / Max / Team subscription is used through Claude Code's auth.

**Client wrapper** (`client.py`) — two interchangeable transports:

1. **`claude_cli` (default)** — shells out to the `claude` binary in headless mode:
   ```
   claude -p "<prompt>" \
          --output-format json \
          --append-system-prompt @profile/system_prompt.md \
          --max-turns 1 \
          --permission-mode auto \
          --disallowed-tools Bash,Edit,Write,Agent
   ```
   - `-p / --print` prints the assistant message and exits (no interactive REPL).
   - `--output-format json` returns a structured envelope `{result, total_cost_usd, num_turns, session_id, ...}` so the wrapper can log usage without parsing prose.
   - `--append-system-prompt` is generated from `profile/resume.md + skills.md + preferences.yaml + answers.yaml`. Claude Code's internal prompt cache keys on it, so repeated calls within the same scoring batch are cheap.
   - Tools are disallowed because the LLM layer only does text→text; we don't want Claude editing files during scoring.
   - The wrapper enforces a 60s timeout per call and retries once on transient errors.

2. **`agent_sdk` (fallback / future)** — uses the **Claude Agent SDK** Python bindings (`pip install claude-agent-sdk`) for in-process invocation, same auth, no subprocess overhead. Selected when the env detects the SDK is installed; falls back to `claude_cli` otherwise. Same input/output shape so call sites don't change.

**Auth model** — Claude Code reads its credentials from `~/.claude/` (set up once with `claude login` or by signing in through the desktop app). The backend just inherits the user's home directory; the FastAPI process needs to run as the same user. No tokens travel through `.env` or the DB.

**Profile system prompt** (`profile/system_prompt.md`, generated) — concatenation of resume, skills, preferences (relevant slice), and screening answer cheat-sheet. Regenerated whenever any source file changes (watcher updates `profile_state.content_hash`). Kept identical across the scoring batch so Claude Code's prompt cache hits.

**Structured output** — Claude Code returns the assistant's text in the `result` field of the JSON envelope. The wrapper expects each prompt to instruct Claude to emit a fenced ```json block; a small parser extracts the first JSON block, validates it with pydantic, and re-prompts once on failure.

**Scoring prompt** (`scoring.py`): JD in → `{score: 0-10, rationale, red_flags: [str], match_highlights: [str]}` out.

**Cover letter** (`cover_letter.py`): tailored 150–200 word letter, 2–3 specific JD references, matching resume bullets. Stored in `applications.cover_letter_md`.

**Screening** (`screening.py`): list of `{question, type, options?}` from the apply handler → list of `{answer, confidence, source: "answers.yaml"|"resume"|"synthesized"}`. Confidence < 0.8 → handler routes the job to `needs_human` instead of submitting a guess.

**Cost tracking** — `total_cost_usd` from each Claude Code invocation is summed into the `metrics` table for the dashboard, so the user can see "this week cost ~$0 because it's all included in your Claude Max plan" or actual spend if on a usage-billed plan.

### 8.4 Apply handlers (`app/apply/`)

```python
class ApplyHandler(Protocol):
    source: str
    async def can_handle(self, job: Job) -> bool: ...
    async def apply(self, job: Job, profile: Profile) -> ApplyResult: ...
```

Resolution order: `linkedin_easy` → `greenhouse` → `lever` → `workday` → `generic`.

**Common behaviors** (in `base.py`):
- Apply is the **only** place Playwright runs in this system.
- Always launch via persistent context for the source (cookies/session live in `browser_state/<source>/`).
- Take a screenshot on every error; save under `logs/screenshots/`.
- Human-like delays: 200–800ms between fields, 1–3s between pages.
- Respect `limits.max_applications_per_*_per_day` — checked from DB before each apply.
- On detection of a CAPTCHA / 2FA / "verify you're human": abort, set status `needs_human`, notify.

**LinkedIn Easy Apply** (`linkedin_easy.py`):
- Open job URL → click "Easy Apply".
- For each modal step: detect input types, fill from `profile` and `answers.yaml`; for unknown questions call `llm.screening`.
- Upload `resume.pdf` if a file input is present.
- Click "Review" → "Submit". Capture confirmation text.
- If at any step a non-Easy-Apply path is detected (external "Apply on company site"), abort to `generic` handler with the external URL.

**Greenhouse / Lever**: clean form selectors; mostly deterministic. Resume upload, basic fields, optional cover letter textarea.

**Workday** (best-effort): account creation per company is the painful part. v1 supports applying when the user already has an account in `browser_state/workday-<company>/`; otherwise → `needs_human`.

**Generic**: heuristic form filler. Detects fields by `label`/`name`/`placeholder`/`autocomplete`. Uploads resume if a file input matching `/resume|cv/i` exists. Best-effort; flags low-confidence submissions.

### 8.5 Scheduler (`app/scheduler/`)

APScheduler with SQLAlchemy jobstore (so jobs survive restarts). Three recurring jobs:

| Job | Default schedule | Action |
|---|---|---|
| `search` | every 6h, weekdays 9–21 IST | hit each enabled source over API/MCP in parallel, upsert into `jobs` |
| `score` | every 10 min when `new` rows exist | batch score up to 20 rows per tick |
| `apply` | every 5 min | pick up to N `approved` rows respecting daily limits; uses Playwright |
| `export` | daily 23:55 local | write `logs/exports/YYYY-MM-DD.xlsx` |
| `digest` | daily 09:00 local | email digest with the previous day's Excel attached |

All schedules are configurable from the UI (writes to a `schedules` table that the scheduler watches).

### 8.6 Web UI

Designed for one user on `127.0.0.1:8000`. Goal: from "fresh clone" to "first application submitted" in under 10 minutes, with no editing of YAML files by hand.

#### 8.6.1 Design system

- **Stack**: Jinja templates + HTMX + Tailwind + Alpine.js (tiny — only for client-side interactions like dropdowns/toggles). No build step required (Tailwind via standalone CLI).
- **Layout**: persistent left sidebar (logo + nav), top bar (run-status pill + manual "Run search now" / "Run apply now" buttons + global toast area), main content.
- **Theme**: dark mode default (matches the screenshot you shared), light mode toggle. Neutral grays + a single accent color (blue for actions, green for applied, amber for needs-human, red for failed).
- **Typography**: Inter for UI, JetBrains Mono for code/JSON.
- **Density**: comfortable on dashboard, compact on tables; sticky table headers; keyboard-friendly (`j`/`k` to move between queue rows, `a` approve, `r` reject, `?` shortcuts modal).
- **Realtime**: every list page subscribes to `/api/events` (SSE). Status pills update live without refresh.

#### 8.6.2 First-run onboarding wizard (`/setup`)

Shown automatically when `profile_state` is empty. Five steps with a progress bar; user cannot skip but can go back.

1. **Welcome & Claude Code check** — explains what the app does in 4 bullets. Backend runs `claude --version` and `claude -p "ok"` to confirm Claude Code is installed and the user is logged in. **No API key is collected** — all LLM calls go through the user's existing Claude subscription. If the check fails, the UI shows "Install Claude Code" / "Run `claude login`" instructions with a re-check button.
2. **Upload resume** — drag-and-drop zone accepting **PDF, DOCX, MD, or TXT**.
   - PDF/DOCX → extracted to markdown via `pypdf` / `python-docx` and shown in a preview pane the user can edit before saving.
   - MD/TXT → shown as-is.
   - Saved to `profile/resume.md`. The original PDF (if uploaded) is also kept at `profile/resume.pdf` and reused for application uploads.
   - "Re-render PDF from markdown" checkbox (off by default) — only on if user wants pandoc-rendered output.
3. **Skills** — single textarea (markdown), with an "Auto-extract from resume" button that calls Claude to suggest a skills list the user can edit.
4. **Preferences form** — see §8.6.3 below. All structured inputs, no YAML.
5. **Connect sources** — toggles for Indeed/Dice (MCP), Greenhouse/Lever (paste company slugs), LinkedIn (choose Apify or RapidAPI + paste API key, "Test connection" button). Gmail SMTP for digests is optional and last.

On finish, writes `profile/preferences.yaml`, `profile/answers.yaml` (with sensible defaults the user can edit later), `.env`, and triggers the first search run. Lands on the dashboard.

#### 8.6.3 Preferences form (`/profile/preferences`)

A single page, sectioned card layout, autosaves on blur (HTMX `hx-trigger="change delay:400ms"`). Each section maps 1:1 to a block in `preferences.yaml`:

| Section | Inputs |
|---|---|
| **Identity** | full name, email, phone, current location, work authorization (free text), LinkedIn URL, GitHub URL, portfolio URL |
| **Targeting** | titles (chip input — type and press Enter), seniority (multi-select), experience min/max (number sliders), locations (chip input), work modes (checkbox group: Remote / Hybrid / Onsite), CTC min/target (number with currency selector) |
| **Filters** | must-have keywords (chips), nice-to-have (chips), blacklist keywords (chips), blacklist companies (chips), max posting age (number + days/hours toggle) |
| **Scoring** | min score to qualify (slider 0–10), auto-apply threshold (slider with explicit "Off / require manual approval" option) |
| **Daily limits** | total/day, per-source/day (rows for each enabled source) |
| **Schedules** | cron-style picker for search / apply / digest with friendly presets ("Every 6h, weekdays 9–9", "Twice daily", "Custom…") |

Each chip input supports paste of comma-separated values. Each numeric input shows the unit inline (₹, yrs, hrs). A right-rail "Live YAML" panel (collapsible) shows the generated `preferences.yaml` so power users can see exactly what's saved — read-only by default with an "Edit raw" toggle for advanced edits. Validation runs on every change; invalid sections highlight in red with inline messages.

**Screening answers** live on a sibling tab `/profile/answers` with the same card pattern, pre-populated with common questions (work auth, sponsorship, notice period, current/expected CTC, willing to relocate, EEO). Users can add custom Q→A pairs.

#### 8.6.4 Resume management (`/profile/resume`)

- Two-pane editor: left is a file picker / version list, right is a markdown editor with live preview (using `marked.js`).
- Buttons: **Replace from upload**, **Render to PDF**, **Download PDF**, **Restore previous version** (we keep the last 5 in `profile/_versions/`).
- "Tailored variants" tab (v0.4): create per-role-family variants tagged by keyword; the scorer picks the best variant per job at apply time.

#### 8.6.5 Dashboard (`/`)

Top row of stat cards (live):

```
┌───────────────┬───────────────┬───────────────┬───────────────┐
│ Today applied │ Queue waiting │ Needs human   │ Failed (24h)  │
│      4 / 15   │      7        │      2        │      1        │
└───────────────┴───────────────┴───────────────┴───────────────┘
```

Below: two columns —
- **Recent activity timeline** (left, 60% width): a stream of events like "10:14 — Applied to Senior Python Engineer @ Stripe via Greenhouse · score 8.7", with status icons. Clickable rows open the job detail modal.
- **Source health** (right): each source shows last run time, count of jobs found, error indicator. Manual "Run now" button per source.

Below that: a 7-day sparkline of applications/day, success vs failed.

#### 8.6.6 Approval queue (`/queue`)

The most-used page. Purpose: skim ~10–20 cards in 2 minutes, approve the good ones.

Each card shows:
- Title · Company · Location · Work mode · CTC range
- Score (large, color-coded)
- Top 3 match highlights and any red flags (from the scoring LLM)
- Posted X days ago · Source badge
- 2-line JD excerpt with "Show full JD" expand
- Buttons: **Approve & Apply**, **Approve & Edit cover letter**, **Reject** (with reason dropdown — "not interested", "wrong location", "low pay", "other"), **Snooze 7 days**

Bulk select via checkboxes → bulk approve / reject toolbar. Filter chips at top: source, score range, posted-within, work mode. Sort: score desc (default), newest, oldest.

#### 8.6.7 Job detail (`/jobs/{id}`)

Three-tab modal/page:

1. **Overview** — full JD, score breakdown, generated cover letter (editable inline), application timeline.
2. **Screening preview** — for not-yet-applied jobs, shows what the LLM *would* answer to common screening questions; user can override.
3. **Run logs** — raw timeline of the apply attempt, screenshots gallery, copy-as-curl-equivalent for debugging.

#### 8.6.8 Jobs explorer (`/jobs`)

Paginated table over all jobs. Columns: status badge, score, title, company, source, location, posted, discovered, actions. Rich filters in a left rail (saved filter presets). CSV export button (in addition to the daily Excel digest).

#### 8.6.9 Runs (`/runs`)

Reverse-chronological list of search/score/apply/export/digest runs. Each row expands inline to show the run's markdown log. Failed runs are flagged red with a "Retry" button.

#### 8.6.10 Settings (`/settings`)

Tabs: **Sources** (toggle + per-source config + test connection), **API keys** (masked, with rotate button — writes to `.env` atomically), **Schedules** (visual cron editor), **Notifications** (Gmail SMTP, optional Discord/Telegram webhook), **Backup** (download `data/jobs.db` + `profile/`, restore from zip), **Danger zone** (reset DB, clear browser_state).

#### 8.6.11 Accessibility & UX details

- All actions have keyboard shortcuts (visible via `?`).
- Toast notifications for every backend action (success/error), with undo where possible (e.g. undo a reject within 10s).
- Empty states are illustrated and link to the relevant setup step.
- Long actions (Apify run, Playwright apply) show a progress drawer at the bottom-right with cancel.
- Mobile: dashboard + queue are responsive (one-column, swipe to approve/reject); full editing is desktop-only.

#### 8.6.12 End-to-end user flow

```
1. Open http://127.0.0.1:8000  →  /setup wizard (5 steps, ~7 min)
        ↓
2. Wizard finishes  →  first search run kicks off automatically
        ↓
3. ~30s later, dashboard shows "12 new jobs scored"
        ↓
4. User opens /queue, skims cards, clicks Approve on 5 of them
        ↓
5. Apply worker picks them up over the next ~10 min, submits via Playwright
        ↓
6. Dashboard timeline updates live; failures get a screenshot link
        ↓
7. 23:55 — Excel exported  ·  09:00 next day — digest email arrives
        ↓
8. Repeat. User only ever touches /queue + occasionally /profile.
```

The user never edits YAML, never opens a terminal after install, and only sees CLI-level details if they actively click into `/runs` for debugging.

### 8.7 Notifications (`app/services/notify.py`)

- **Daily digest** at 09:00 local: summary of last 24h (applied, pending approval, failures). Sent via Gmail SMTP (`GMAIL_APP_PASSWORD` in `.env`). **Attaches the day's Excel export** (see §8.8).
- **Immediate alerts** on `needs_human` outcomes: same channel.
- Optional webhook (Discord/Telegram) for the impatient.

### 8.8 Daily Excel export (`app/services/export.py`)

A scheduled job at 23:55 local writes `logs/exports/YYYY-MM-DD.xlsx` using `openpyxl`. Workbook contains four sheets:

| Sheet | Columns |
|---|---|
| **Searched** | discovered_at, source, company, title, location, work_mode, ctc_min, ctc_max, url, score, status |
| **Applied** | applied_at, source, company, title, url, cover_letter_excerpt, confirmation_text |
| **Failed** | attempted_at, source, company, title, url, failure_reason, screenshot_path |
| **Needs Human** | flagged_at, source, company, title, url, reason |

The same export is attached to the next morning's digest email. The file is also linked from the `/runs` page in the UI. A weekly rollup `logs/exports/week-YYYY-WW.xlsx` is produced on Sundays.

---

## 9. Configuration & Secrets

### 9.1 `.env` (gitignored)

```
# No ANTHROPIC_API_KEY — LLM calls use the local `claude` CLI / Agent SDK,
# which inherits the user's Claude Code login from ~/.claude/.

# LinkedIn search — set the one you use; the other can stay blank.
APIFY_TOKEN=apify_api_xxx                # default mode
RAPIDAPI_KEY=xxx                          # fallback mode

GMAIL_ADDRESS=jhanitin906@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
APP_SECRET=<random 32 bytes>             # only used if remote-access mode is enabled
DB_PATH=./data/jobs.db
LOG_LEVEL=INFO

# LLM transport selection
CLAUDE_TRANSPORT=claude_cli              # claude_cli | agent_sdk
CLAUDE_BIN=claude                         # path or name of the Claude Code binary
```

### 9.2 `.gitignore` (must contain)

```
.env
.env.*
!.env.example
data/
browser_state/
logs/
profile/resume.pdf
*.db
*.db-journal
__pycache__/
.venv/
node_modules/
```

### 9.3 GitHub PAT in `token` file

The existing `/home/nitin/Desktop/auto-job-apply/token` file containing a GitHub PAT must be:
1. Added to `.gitignore` immediately.
2. Rotated on GitHub.
3. Moved into `.env` if still needed (`GITHUB_PAT=...`), never re-committed.

---

## 10. Security & Safety

1. **Localhost-only binding**. `uvicorn --host 127.0.0.1 --port 8000`. To access remotely, use Tailscale rather than exposing the port.
2. **Secrets in `.env`**, loaded via `pydantic-settings`. Never logged. Never written to DB.
3. **Browser state** (`browser_state/`) contains live session cookies — gitignored, mode `0700`.
4. **Approval queue is the default**. `auto_apply_threshold: null` until the user explicitly enables auto-apply per source.
5. **Daily caps** enforced in the apply worker before each submission to prevent runaway loops.
6. **LinkedIn-specific care**: low volume, jitter, persistent IP (no VPN switching mid-run), abort on any anti-bot challenge.
7. **Screening answer audit**: every LLM-generated answer is logged with its prompt and confidence; the user can review in `/jobs/{id}`.
8. **No silent overwrites** of resume/profile files from the UI — edits go through a draft-then-confirm flow.

---

## 11. Local Setup

```bash
# 1. Clone and enter
cd ~/Desktop/auto-job-apply

# 2. Python env
python3.11 -m venv .venv
source .venv/bin/activate.fish    # fish shell
pip install -e ".[dev]"

# 3. Browsers
playwright install chromium

# 4. Secrets
cp .env.example .env
# fill in ANTHROPIC_API_KEY, GMAIL_*

# 5. Profile
$EDITOR profile/preferences.yaml
$EDITOR profile/answers.yaml
$EDITOR profile/resume.md
python scripts/render_resume.py     # produces profile/resume.pdf

# 6. First-time browser logins (manual, one-off per source)
python scripts/login.py linkedin
python scripts/login.py indeed
# ...stores cookies into browser_state/<source>/

# 7. DB
alembic upgrade head

# 8. Run
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000`.

For always-on operation, install the systemd user unit at `deploy/auto-job-apply.service`:

```ini
[Unit]
Description=Auto Job Apply
After=network.target

[Service]
WorkingDirectory=%h/Desktop/auto-job-apply
ExecStart=%h/Desktop/auto-job-apply/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=default.target
```

`systemctl --user enable --now auto-job-apply`.

---

## 12. Claude Integration (3 modes, all local)

This system uses Claude in three distinct roles. They don't conflict.

### 12.1 Claude Code headless (primary runtime path) — no API key

The scheduler and apply workers invoke `claude -p "<prompt>" --output-format json ...` (or the Claude Agent SDK equivalent) for scoring, cover letters, and screening answers. This uses the user's existing Claude Code subscription via `~/.claude/` auth — no `ANTHROPIC_API_KEY`, no separate account, no extra billing.

Operationally:
- A health-check on app startup runs `claude --version` and `claude -p "ping"` to verify the binary is installed and logged in. If not, the UI surfaces a setup banner with a "Run `claude login` in your terminal" instruction.
- Each call is short-lived (`--max-turns 1`, 60s timeout, tools disabled). The LLM never has Bash/Edit/Write access during scoring or cover-letter generation.
- Profile content lives in `--append-system-prompt @profile/system_prompt.md`, which Claude Code's prompt cache de-duplicates across calls in the same batch.

### 12.2 Claude Code CLI (developer workflow)

The user opens this repo with `claude` in the terminal for development, debugging, adding new source/apply handlers. Same auth as the runtime path — but interactive.

### 12.3 Claude Routines UI (optional cloud companion)

A separate, optional cloud routine (configured in claude.ai) can run **search-only** flows using the Indeed/Dice/Gmail connectors and POST results to the local app's `/api/jobs/ingest` endpoint over Tailscale. Additive; the local system is fully functional without it.

> Note: cloud routines **cannot** run Playwright. All apply actions stay local.

---

## 13. Testing Strategy

- **Unit**: dedupe, canonical URL stripping, scoring JSON parsing, screening answer resolution. Pure-Python, fast.
- **LLM contract tests**: replayed fixtures using `vcrpy`-style cassettes; ensures prompt changes don't silently break JSON shape.
- **Playwright integration**: each source/apply handler has a smoke test against a recorded HAR or a sandbox board (Greenhouse demo, Lever demo). LinkedIn/Indeed tests are gated behind `RUN_LIVE=1` and skipped in CI.
- **Manual QA checklist** in `tests/manual_qa.md` for first run after schema or handler changes.

---

## 14. Observability

- Structured logs (JSON) via `structlog`; one log file per day under `logs/`.
- Per-run markdown summary in `logs/runs/YYYY-MM-DD-HHMM-<kind>.md` linked from `/runs`.
- Failure screenshots in `logs/screenshots/`.
- Lightweight metrics counter in SQLite (`metrics` table): applications/day, success rate, avg score, avg LLM tokens, avg cost. Surfaced on the dashboard.

---

## 15. Roadmap

### v0.1 — MVP (week 1–2)
- FastAPI skeleton + SQLite + HTMX dashboard.
- Sources: Greenhouse + Lever (HTTP only — no browser).
- LLM scoring + cover letter generation.
- Apply handlers: Greenhouse + Lever.
- Approval queue, no auto-apply.
- Manual run buttons; basic scheduler.

### v0.2 — Browser sources (week 3)
- Playwright + persistent context infra.
- LinkedIn search scraper.
- LinkedIn Easy Apply handler.
- Login script.
- Daily digest email.

### v0.3 — Coverage (week 4)
- Indeed + Dice scrapers.
- Workday handler (existing-account mode).
- Generic ATS form filler.
- Resume PDF auto-render on `resume.md` change.

### v0.4 — Quality of life
- Auto-apply gate per source with score threshold.
- Cover letter editor in queue view.
- Multi-resume support (per role family).
- Optional cloud routine integration via `/api/jobs/ingest`.

### Later
- Salary intel: pull market data, flag underpaid roles.
- Interview tracker: linked outcomes per application.
- Browser extension to one-click ingest a JD from any page into the queue.

---

## 16. Open Questions

1. **Resume rendering**: pandoc + LaTeX template, or a Markdown→HTML→Chromium-print pipeline? The latter is simpler and avoids LaTeX deps.
2. **Multi-resume**: per-role-family selection at scoring time, or per-job rewrite by the LLM? Probably both: pick base resume by tag, then optionally tweak the summary line for the specific JD.
3. **LinkedIn login durability**: cookies typically survive 2–4 weeks. Acceptable to require monthly manual re-login, or invest in Chrome profile import?
4. **Storage of generated cover letters**: keep all of them forever, or prune after N days? Default: keep — they're tiny and useful for follow-ups.
5. **Two-machine setup**: if the user wants the app reachable from phone, do we add Tailscale instructions or build a minimal magic-link auth? Tailscale recommended.

---

## 17. Glossary

- **Job hash**: stable dedupe key per posting.
- **Persistent context**: a Playwright `BrowserContext` backed by a directory on disk so cookies/localStorage survive between runs.
- **Approval queue**: the set of `qualified` jobs awaiting the user's explicit approve/reject.
- **Apply handler**: source-specific Playwright routine that submits an application.
- **Screening question**: any non-resume question presented during application (years of X, salary, work auth, EEO).
