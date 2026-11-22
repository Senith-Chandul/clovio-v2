# Clovio v2

An AI-based collaboration and management tool for teams. This is a rebuild of Clovio, a university group-project tracker ("students and supervisors", "fair workload"), as a general tool whose focus is **getting the work done efficiently**.

The old app is at `../clovio-platform` (GitHub `SDGP-Clovio/clovio-platform`, branch `fix/audit-fixes`, latest commit `d9ed1a4`, not pushed, no PR). Treat it as the reference implementation: port what works and leave the student and university parts behind.

## The client brief (received Fri 20 Nov 2026)

A client saw the demo and will pilot Clovio to **manage an event they are organising**. Everything below has to work by **Monday 23 Nov 2026**:

1. **Every feature actually works.** No simulated integrations and no canned "AI" text (the old app had both, see "Fake in the old app").
2. **Sign in with Google and/or Microsoft.**
3. **Connect calendars.** Meetings go into people's calendars, and people's free time informs scheduling.
4. **Efficiency over fairness.** The AI assigns work so the project finishes soonest, not so everyone gets an equal share.
5. **A general collaboration tool.** Members, managers and owners, not students and professors.

Questions still to put to the client. They decide what gets built first:
- Do they use Google Workspace, Microsoft 365, or personal Gmail/Outlook? Build that provider first.
- The pilot users' emails (Google test mode only lets listed users sign in).
- Who the managers are.
- The event date, and the brief to feed the AI wizard.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2, Alembic, Postgres on Supabase, psycopg 3, PyJWT. Dev passwords use the standard library's scrypt.
- **Frontend:** React 19, Vite 7, Tailwind CSS v4 (`@tailwindcss/vite`, no `tailwind.config.js`), TypeScript, axios, react-router 7, and TanStack Query for server state (caching, polling, optimistic edits).
- **API types are generated, never hand-written:** `npm run gen:api` (with the backend running) writes `frontend/src/api/schema.d.ts` from FastAPI's OpenAPI schema; `src/api/types.ts` names the ones in use.
- **AI:** Groq (`openai/gpt-oss-120b`), with DeepSeek as an optional first-choice provider. Groq Whisper for voice commands (its model name from env too).
- **Sign-in and calendars:** plain httpx for OAuth, Google Calendar and Microsoft Graph (no vendor SDKs, no Authlib), PyJWT to check ID tokens, and `cryptography` (Fernet) to encrypt stored refresh tokens. Briefs: pypdf for PDF, and the standard library for DOCX.
- **Hosting plan:** backend on Render or Railway, frontend on Vercel, database on Supabase. OAuth redirect URIs must be HTTPS (localhost is the only exception), so deploy early.
- **Dev machine:** Windows, Git Bash and PowerShell. The Python venv lives in `backend/venv`. Application control blocks new compiled builds there: see gotchas 11 and 12.

## Data model

`backend/app/models.py` is the source of truth and `backend/alembic/versions/` holds the migrations. The decisions behind it:

- **Everything hangs off a project.** Access is always checked through `project_members`, so organisations or workspaces can come later as one table and one `projects` column.
- **Roles are per project:** owner, manager, member. Any member can create and update tasks; managers and owners can also delete tasks, rebalance, and manage people.
- **An invite is a user row** with no password (`last_login_at` stays null until they sign in), so work can be assigned before they sign in. There is no invites table.
- **Hours, not points:** `tasks.estimate_hours`, because free time (calendars, `users.weekly_hours`) is measured in hours.
- **One task-status list end to end:** `todo / in_progress / blocked / done` (`TaskStatus`). The old app had `todo/doing/done` in the backend, `in-progress` in the frontend and `in_progress` in the AI schemas, with mapping code everywhere.
- **`task_events` is the history, the comments (`kind=note`) and the voice log in one table**, each row with a `source` (app, ai, voice). Cycle time, undo and "who changed this" read from it.
- **`assignee_locked`:** a person chose the assignee, so rebalancing leaves that task alone.
- **Derived, not stored:** progress, milestone status and effort, metrics.
- **Portable types:** UUID keys (the browser can create a new task's id, so there's no temp-id swapping), lists as JSON, enums stored as plain text. Tests run on SQLite; production is Postgres.

## Auth and calendars

- **Sign-in flow** (`services/oauth.py`, routes in `api/auth.py`): `/api/auth/{provider}/start` redirects to Google or Microsoft (Microsoft uses the `common` endpoint, so work and personal accounts both work) with PKCE and a nonce. A signed cookie, valid for 10 minutes, carries the state between start and callback. The callback exchanges the code with plain httpx, checks the ID token with PyJWT (signature against the provider's JWKS, audience, issuer, nonce), finds the user by provider subject, else by **verified** email (which claims an invited user's row), else creates one, and sends the browser to `/auth/callback#token=…` in the web app. Failures go to `/login#error=…`.
- **Verified email only:** Google sends `email_verified`. Microsoft's `email` claim can be unverified, so it's trusted only with `xms_edov` or from the personal-accounts tenant. Otherwise anyone with their own tenant could claim an invited person's account. **The Entra app needs the optional ID-token claims `email` and `xms_edov`**, or work accounts can't sign in.
- **Connecting a calendar while signed in** (Settings): `POST /api/calendars/{provider}/connect` returns a start URL with a 5-minute link ticket, because a browser navigation can't carry the bearer token. The ticket has no `sub`, so it can't be used as a login. One account per provider per person.
- **Password login:** dev and demo accounts only. Sign-up is behind `ALLOW_SIGNUP=true` (off in production) and never claims an existing user row. No "forgot password".
- **Scopes:** asked for at sign-in, with offline access for a refresh token. Google: `openid email profile` plus `calendar.events` and `calendar.freebusy` (busy blocks only, never event details), with `prompt=consent`, since Google only sends a refresh token on the consent screen. Microsoft: `openid email profile offline_access Calendars.ReadWrite`.
- **Tokens:** refresh tokens are Fernet-encrypted (`TOKEN_KEY`, or derived from `SECRET_KEY`). Access tokens are cached in memory. A refresh that returns `invalid_grant` sets `needs_reconnect`, which Settings shows as Reconnect; a network error doesn't.
- **Creating a meeting** (`api/calendars.py`): one event in the organiser's calendar with the attendees' emails. Google (`sendUpdates=all`) and Outlook then send the invites, so only the organiser needs a connected calendar. Attendees get a Clovio notification too. Only the organiser can cancel, because cancelling goes through their calendar.
- **Free/busy** (`services/calendars.py`): each person's own token reads their own calendar: Google `freeBusy`, and Outlook `calendarView` with only start, end and showAs (`getSchedule` doesn't support personal accounts). It reads 6 weeks ahead, cached for 10 minutes per person, and a failure counts as "unknown", never as an error. It feeds:
  - the scheduler: busy time inside the person's 9:00–17:00 local day lowers that day's 8-hour cap;
  - "Suggest a time": weekday slots in the organiser's working day that are free for everyone with a calendar, at most two a day, naming the people whose calendars couldn't be read.
- **Time zones:** the web app sets `users.timezone` from the browser.

## What "efficient" means

- **The AI writes the plan; code assigns the work.** The LLM writes milestones (with dates) and tasks with hour estimates, required skills (in the team's own skill words where it can) and dependencies. Tasks get no date from the AI: they use their milestone's, unless a person sets one. (In live tests the AI's per-task dates were guesses spread across the milestone and flagged half the plan "at risk".) Milestone titles go through `_sentence_case`, because the model writes Title Case whatever the prompt says. A deterministic scheduler (plain Python, covered by pytest) assigns them:
  1. Order tasks by dependencies, then due date, then size.
  2. Candidates are the members with the best skill match; no match at all flags a skill gap (and anyone may take it).
  3. Walk each candidate's free hours day by day: their weekly hours are a budget for each 7-day block from today (at most 8 hours in one day, not an even 1/7 a day), minus calendar busy time, minus work already assigned in any project. That gives the day they'd finish.
  4. The task goes to whoever finishes first. If no best match can make the due date but someone with a weaker match can, they get it (finishing on time beats a perfect match). If nobody makes it, it's flagged at risk with both dates.
  5. The reason shown is built from those numbers, never written by the AI.

  `backend/app/services/scheduler.py` (`plan()` is pure; `tests/test_scheduler.py`). The task list runs it on every read with nothing movable, to forecast each task's finish and flag what's at risk.

  "Rebalance" reruns it on unstarted, unlocked tasks and previews what would move. This replaces the old "balance cumulative complexity" rules.
- **Metrics:** on-time rate, overdue count, cycle time (in progress to done, from `task_events`), bottlenecks (a person whose open hours exceed their free time before the deadline), and predicted finish against the deadline (from the same scheduler run).
- **Workload bars:** the design system's workload bars stay, but the dashed line shows each person's **capacity**, not a fair share.
- **Compute on the server:** metrics are calculated when they're read. The old frontend re-posted the whole task list to `/fairness/compute` and `/progress/compute` on every change.

## Project creation (the wizard)

1. **Describe:** the brief (pasted, or a PDF/DOCX/TXT whose extracted text is shown in the box), the deadline, and people's emails (skills and hours optional). Creates the project in `planning` status.
2. **Clarify:** up to three questions from the AI, skippable; skipped entirely when it has none.
3. **Plan:** milestones first, with dates worked back from the deadline. Then one AI call per milestone, run in parallel, each saved straight into the project in one transaction. The scheduler assigns. A milestone that fails gets its own Retry.
4. **Review:** the plan opens in the normal list view with the normal task tools, plus a box to "ask Clovio to change the plan".
5. **Start:** status becomes `active`, and only then are people notified.

## Task changes and voice

- **One write path:** every task change (board, task drawer, bulk edit, AI, voice) goes through one service that checks permission and writes the change, a `task_events` row and any notifications in one transaction.
- **Views:** board, list (inline edit, bulk edit), timeline (by due date), and My tasks across projects (the phone view, with the mic). One task drawer, with its own URL. Every change shows Undo. Every card has a status menu, since drag-and-drop is unreliable on phones.
- **Voice and the command bar:** `POST /projects/{id}/assist` takes audio (Groq Whisper turns it into text) or typed text. The LLM gets the open tasks, the speaker's first, and must reply with a fixed set of actions: update status, hours, due date or assignee; add a note; create a task; answer a question; or ask which task. The server checks every action (only task ids it sent, valid values, permission) and applies it through the one write path. One clear match: apply it and show Undo. Two possible matches: ask. Never delete by voice. Audio isn't stored; the transcript goes into the task history.

## Design system

Use the Clovio design system: https://claude.ai/artifact/MWAvb9f5HcyqgTCM22Tbtg (read it with the Artifact tool's `read` action).

Ported from the old app:
- `frontend/src/index.css` holds the tokens on `:root` and `[data-theme="dark"]`, and the `@theme inline` mapping to Tailwind. It also has the `clv-*` component classes in `@layer components`.
- Components: `src/layout/AppShell.tsx` (sidebar and header), `src/ui/{Ring,Gauge,Avatar,Badge,Modal}.tsx`, and `src/brand/{AuthLayout,CoverArt,ClovioMark}.tsx`.

The rules:
- The page background is slate-100. Panels are white, borderless and have large radii. Controls are pills. The font is Plus Jakarta Sans.
- A row of stat tiles has at most one spotlight tile and one positive tile.
- The sparkle icon means AI/Assist and nothing else.
- No emoji, gradients or left-border cards.
- Sentence case everywhere.

## Gotchas learned on the old app

1. **Groq retires models.** `llama-3.3-70b-versatile` vanished and every AI call failed with `model_not_found`. Read the model name from the `AI_MODEL` env var.
2. **gpt-oss is a reasoning model, and its thinking counts against `max_tokens`.** On a 42-point milestone it used up the 4096-token budget and returned an **empty** answer. Pass `reasoning_effort="low"` for gpt-oss, set max_tokens to 8192, and raise a clear error on empty content (log `finish_reason`).
3. **AI endpoints should be plain `def`, not `async def`.** The Groq call blocks, so FastAPI must run it in its thread pool.
4. **Don't create milestones as a side effect of saving tasks.** The old backend found or created a milestone by title on each task POST, so saving tasks in parallel raced and could create duplicates. Save a whole generated plan in **one request and one transaction**.
5. **Don't use the AI's task numbers as client ids.** The old temp ids (`milestone*100+n`) clashed with real task ids in optimistic updates. Use temp UUIDs and swap in the server ids.
6. **Saving a plan one task at a time took about 20 seconds** (sequential awaits plus artificial delays). Batch it.
7. **Supabase connection:** use the **Session pooler** URL and rewrite `postgres://` to `postgresql+psycopg://`, because SQLAlchemy otherwise looks for psycopg2.
8. **Windows console output:** set `PYTHONIOENCODING=utf-8` before printing AI output. It contains characters such as `‑` that crash cp1252.
9. **Check whether uvicorn auto-reloads.** If the backend runs without `--reload`, restart it after backend changes, or you'll be testing old code. On the dev machine `--reload` (StatReload) can lag by minutes and once restarted in the middle of a test run: restart the server yourself before testing a backend change.
10. **Startup checks:** refuse to start without a real `SECRET_KEY`, and allow localhost CORS on any port plus `ALLOWED_ORIGINS` from the environment.
11. **Windows application control on the dev machine blocks new builds of compiled packages** (`.pyd`, `.node`, `.dll`: "An Application Control policy has blocked this file") and pip's generated `.exe` launchers. Keep the pins in `backend/requirements.txt` and `frontend/package-lock.json`, which match builds the machine already allows, and run tools as `venv/Scripts/python.exe -m pytest` (or `alembic`, `uvicorn`).
12. **esbuild.exe can't open `.js` files on the dev machine** (security software). `vite.config.ts` has Node read them during the dev server's pre-bundling. Files can also be locked for a few seconds just after an install; retry.
13. **email-validator rejects reserved domains** such as `.test` and `.localhost`. Use `example.com` addresses for test accounts.
14. **Vite's file watcher can miss the second of two quick edits** to one file, and keeps serving the stale module (for example "ReferenceError: X is not defined" for something that is imported). Restart the frontend dev server.

## Fake in the old app (don't port these as they are)

- **AI status report:** it called an Ideamart API whose key was never set, and fell back to canned text dressed up as AI. Route it through the same LLM helper as everything else.
- **Moodle "integrations" page:** simulated. Replace it with "Connected calendars" in Settings.
- **"Forgot password":** the button did nothing.
- **Wizard "attach the brief":** the file was never sent to the backend.
- **Chat:** never refreshed, so other people's messages only appeared after a reload. Poll every few seconds at least.
- **Notifications:** only the current browser session's own actions, never stored.
- **Landing page:** the stats and testimonials were invented (already removed in the old repo; don't bring them back).

## Worth porting from ../clovio-platform

- `backend/app/services/ai_service.py`: the milestone and task prompts, the JSON clean-up, and the DeepSeek-then-Groq fallback with tenacity retries. Rewrite rule 3 of the task prompt (fairness) for efficiency.
- `backend/app/core/{config,auth,database}.py`: settings, JWT, `get_current_user`, `require_project_member`.
- `backend/app/utils/{progress,workload}.py`: progress roll-up and the workload summary given to the AI. Drop `fairness.py` (the Gini index), or keep it only as a secondary signal.
- `backend/scripts/seed_demo.py`: seeds a demo through the API. Adapt it for an event project.

## Deadline plan (rebuild)

- **Fri 20 Nov:**
  - Done: repo, schema and first migration, dev login and JWT, the design system and app shell, TanStack Query and generated API types.
  - Still to do, by the user: the Google Cloud OAuth client (consent screen in Testing, pilot users added as test users), the Microsoft Entra app registration, and a Supabase project for v2.
- **Sat 21 Nov:**
  - Done Friday night: projects and members (invites as user rows), the one task write path (`services/tasks.py`), the list, board, task drawer and people views, bulk edit, undo, rebalance, and the wizard (`services/planner.py`, `services/llm.py`, `features/wizard/`) with the scheduler. 37 backend tests. Tested live with Groq (Sat 21 Nov): a 120-guest launch brief with four people gives 5 milestones and about 27 tasks in about 12 seconds, finishing well before the event; the tasks still at risk are real bottlenecks (one person holding a skill nobody else lists). Known limit: milestones are generated in parallel, so the same work can now and then appear in two milestones; the review step is where people delete it.
  - Done Saturday, pulled forward from Sunday:
    - Voice and the command bar: `POST /api/assist`, `services/assist.py`, and `features/assist/` on the project page (where it is also the plan's "ask Clovio to change it" box) and on My tasks (`/my`).
    - Notifications: written by the task write path (a task given to you; a blocked task, which goes to managers) and when a project starts (one summary each). Draft plans stay quiet. The bell is in the header and polls every 20 s.
    - The Overview tab (`services/metrics.py`, `GET /projects/{id}/overview`): predicted finish against the deadline, done by hours, on-time rate, overdue, median cycle time, workload bars with each person's free hours as the dashed line (bottleneck when open hours exceed it), and milestone progress.
    - 47 backend tests, all checked in the browser too.
    - Google and Microsoft sign-in, connected calendars (Settings), meetings in Google Calendar and Outlook (the Meetings tab), free/busy into the scheduler, and "Suggest a time". 56 backend tests, including fake Google and Microsoft endpoints. Checked in the browser up to the point that needs real credentials.
  - Waiting on the user: the Google OAuth client, the Entra app, and a Supabase project. Once they're in `backend/.env`, test sign-in, connecting, meetings and free/busy with real accounts.
  - Deploy to HTTPS.
- **Sun 22 Nov:**
  - Done: chat (`api/chat.py`, `features/chat/`).
    - Each project gets a team chat when it's created, readable by whoever is in the project.
    - Direct messages work between people who share a project.
    - It polls instead of using websockets: an open chat every 3 s, and the list and the sidebar's unread count every 10 s.
    - Reading a chat marks it read; `conversation_members.last_read_at` holds each person's read state.
    - Shown in the sidebar's Chat page and in each project's Chat tab.
    - 58 backend tests; checked in the browser with two users.
  - Done: the timeline view. The scheduler's slots now carry `start` as well as `finish` (`TaskOut.forecast_start`), so each open task is a bar from planned start to finish, with due dates, milestones, the deadline and weeks marked.
  - Done: invite-only sign-in. Google or Microsoft sign-in creates an account only for invited people or those in `NEW_ACCOUNT_EMAILS` (emails, `@domains`, or `*`).
  - Done: Supabase created and migrated, `render.yaml`, and `frontend/vercel.json`. Google credentials are in `.env`; Microsoft's aren't yet.
  - Tested with a real Google account (localhost):
    - sign-in created the account, with all five scopes granted and the refresh token stored;
    - `freeBusy` read the calendar in about 1 s;
    - a meeting created through the API appeared in Google Calendar, and "Suggest a time" then skipped its slot;
    - the scheduler's busy hours read 1.0 for that day, and 0.0 after `cancel_event` deleted it.
    - Not yet run against real Google: the `DELETE /api/meetings/{id}` route itself (it calls the same `cancel_event`), and everything Microsoft.
  - **Stop adding features at 4 pm.** Then test everything end to end on the deployed site with real Google and Microsoft accounts, and only fix bugs.
- **Mon 23 Nov, morning:** create the client's event project with the wizard from their brief, write a one-page how-to, and demo.

**If Saturday slips, cut in this order:** chat, the timeline view, Microsoft (if the client is on Google), "Suggest a time". Never cut sign-in, the wizard, the scheduler, task editing, Google Calendar or the testing time.

**Not for Monday:** live websockets, a mobile app, separate organisations/workspaces, budget and vendor tracking, email digests.

## Risks to tell the client

- **Google test mode:**
  - At most 100 test users, and only the listed ones can sign in.
  - Refresh tokens for calendar scopes **expire after 7 days**, so users reconnect weekly until Google verifies the app, which takes weeks.
  - The alternative is to publish the app unverified (Audience → Publish app). Any Google account can then sign in, up to 100 users in total, and tokens stop expiring weekly. Users see "Google hasn't verified this app" and must click Advanced → Go to Clovio (unsafe). `NEW_ACCOUNT_EMAILS` still keeps out people who weren't invited.
  - A Google Workspace admin can avoid all of this by creating the app inside their own Workspace with the Audience set to Internal.
- **Microsoft work tenants:** they may need their IT admin to approve calendar access.
- **AI limits:** Groq's free tier has rate limits, so get a paid key before real use.
- **Personal data:** these are real people's calendars. Encrypt stored tokens, ask for the fewest scopes that work, and add a short privacy note.

## Run it

- **Backend** (in `backend/`): copy `.env.example` to `.env` and set `SECRET_KEY` (and `GROQ_API_KEY` for the AI). Then `venv/Scripts/python.exe -m alembic upgrade head` and `venv/Scripts/python.exe -m uvicorn app.main:app --reload`. API docs are at http://localhost:8000/docs. Without `DATABASE_URL` it uses `backend/dev.db` (SQLite).
- **Tests:** `venv/Scripts/python.exe -m pytest`. They use their own temporary SQLite file and never touch `.env`'s database.
- **Frontend** (in `frontend/`): `npm ci`, then `npm run dev` (http://localhost:5173). Run `npm run gen:api` after changing the API, and `npm run build` and `npm run lint` before committing.
- **Schema change:** edit `app/models.py`, run `venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."`, read the generated file, then `upgrade head`.
- **Deploy:**
  - **Database:** Supabase, region Singapore, Data API off. It's migrated: 14 tables, with RLS on, which doesn't affect the backend because it connects as the tables' owner.
  - **Backend:** Render, from `render.yaml` (Blueprint, Singapore, Starter plan). It runs `alembic upgrade head` on every start, as one process.
  - **Frontend:** Vercel, root directory `frontend`, with env `VITE_API_URL` set to the Render URL. `frontend/vercel.json` sends every path to the app.
  - **After the first deploy:** set `API_URL`, `FRONTEND_URL` and `ALLOWED_ORIGINS` on Render. Add `{API_URL}/api/auth/google/callback` (and the Microsoft one) as redirect URIs at the providers.
  - **Local development stays on SQLite** (`DATABASE_URL` is commented out in `.env`). From Sri Lanka each Supabase query takes about 90 ms and a new connection about 1.4 s, so pages took seconds there.
- **Layout:** `backend/app/` has `main.py`, `models.py`, `core/` (config, db, security), `api/` (one router per area) and, from the wizard on, `services/`. `frontend/src/` has `api/` (client and generated types), `features/<area>/` (pages and hooks), `ui/` and `brand/` (design-system components) and `layout/` (the app shell).

## Working rules

- Never print or commit `.env` secrets. Keep `.env.example` current instead.
- Don't push or open PRs unless asked.
- Keep `.claude/` out of commits.
