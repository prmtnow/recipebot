# Instagram Recipe Bot MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Instagram business account that replies to DM'd cooking videos with a complete text recipe, capped at 5 videos per user per day.

**Architecture:** Single FastAPI service. Meta webhooks deliver DM events; the worker downloads the video, uploads it to Gemini (Files API), extracts a recipe, and replies via the IG Send API. SQLite stores message dedup, per-user quotas, spend, and a conversion log.

**Tech Stack:** Python 3.12, FastAPI, httpx, google-genai (model `gemini-2.5-flash`), SQLite (stdlib `sqlite3`), pytest + respx.

**Spec:** `docs/superpowers/specs/2026-11-24-ig-recipe-bot-mvp-design.md`

## Global Constraints

- Quota: 5 videos per user (IGSID) per day (`DAILY_USER_LIMIT=5`).
- Never invent a recipe: on extraction failure or non-cooking video, reply with the sorry text; do not fabricate quantities.
- Reply language: the language spoken in the video; English fallback (enforced by the extraction prompt, not by code).
- Inference must stop when today's spend hits `DAILY_SPEND_CAP_USD`; user gets the "busy" reply.
- Videos over `MAX_VIDEO_MB` (default 64) are rejected before download-cost; quota is consumed at extraction attempt, including failed attempts.
- Outbound reply messages are chunked to at most `MSG_CHUNK_CHARS = 1800` characters, max 2 messages.
- All outbound copy is fixed verbatim: see Task 4 (HINT/SORRY/LIMIT/BUSY texts).

## Review Focus

Spec-implied inputs no single task's happy path covers — each is pinned by a test in the named task:

1. **Text/image/sticker DM (not video)** → short how-to hint reply, no quota consumed (Task 6).
2. **Webhook redelivery of the same message id** → exactly one reply, one quota hit (Task 6).
3. **Oversized video** → sorry reply *before* download, quota not consumed (Task 6).
4. **Gemini errors / timeout / no recipe in response** → sorry reply, quota consumed, nothing invented (Task 6).
5. **Recipe longer than one IG message** → split at a step boundary into ≤2 messages, never mid-ingredient (Task 4).

---

### Task 1: Project scaffold, config, health endpoint

**Files:**
- Create: `pyproject.toml`, `app/__init__.py`, `app/config.py`, `app/main.py`, `tests/__init__.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings` dataclass (`app/config.py`) with fields `ig_access_token: str`, `ig_account_id: str`, `app_secret: str`, `verify_token: str`, `gemini_api_key: str`, `db_path: str`, `max_video_mb: int`, `daily_user_limit: int`, `daily_spend_cap_usd: float` — built by `Settings.from_env(env: Mapping[str, str]) -> Settings`. `create_app() -> FastAPI` (Task 7 takes args; for now no-arg with `/health`).

- [ ] **Step 1: Create `pyproject.toml`** with `fastapi`, `uvicorn[standard]`, `httpx`, `google-genai` as deps and `pytest`, `respx` as dev deps; `[tool.pytest.ini_options] asyncio_mode` left unset (tests are sync; route calls use `fastapi.testclient.TestClient`). Install: `pip install -e ".[dev]"` (create the dev extra).
- [ ] **Step 2: Write failing `tests/test_main.py`**: `test_health_returns_ok` — GET `/health` via TestClient → 200 and body `{"status": "ok"}`.
- [ ] **Step 3: Run** `pytest tests/test_main.py -v` → FAIL (app not defined).
- [ ] **Step 4: Implement `app/main.py`** (`create_app()` returning a FastAPI app with `/health`) **and `app/config.py`** (`Settings.from_env` reading `IG_ACCESS_TOKEN`, `IG_ACCOUNT_ID`, `APP_SECRET`, `VERIFY_TOKEN`, `GEMINI_API_KEY`, `DB_PATH` default `bot.db`, `MAX_VIDEO_MB` default 64, `DAILY_USER_LIMIT` default 5, `DAILY_SPEND_CAP_USD` default 20.0; raise on missing required vars).
- [ ] **Step 5: Add `tests/test_config.py`**: missing required var raises; defaults applied. Run → PASS both files.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: scaffold service, config, health endpoint"`

### Task 2: SQLite store (dedup, quota, spend, log)

**Files:**
- Create: `app/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Store(db_path: str)` with:
  - `mark_seen(message_id: str) -> bool` — True if first time (atomically inserts), False if duplicate.
  - `consume_quota(igsid: str, day: str, limit: int) -> bool` — increments user's counter for `day` (`YYYY-MM-DD`) and returns False (without incrementing) if already at `limit`.
  - `add_cost(cost_usd: float, day: str)` / `today_cost(day: str) -> float`.
  - `log_conversion(igsid: str, message_id: str, status: str, recipe_text: str | None, cost_usd: float)` — status one of `"ok" | "no_recipe" | "error" | "oversized" | "non_video" | "quota" | "busy"`.

- [ ] **Step 1: Write failing tests in `tests/test_store.py`** (use `tmp_path` db, fixed day strings `"2026-11-24"` and `"2026-11-25"`): first `mark_seen` True / second False; `consume_quota` allows 5 for a user and denies the 6th, and counters are per-igsid and per-day; `add_cost` accumulates and `today_cost` returns 0.0 for an untouched day; `log_conversion` round-trips (verify via direct sqlite query).
- [ ] **Step 2: Run** `pytest tests/test_store.py -v` → FAIL.
- [ ] **Step 3: Implement `app/store.py`** — stdlib `sqlite3`, table-per-concern (`seen_messages`, `quotas(igsid, day, count)` with PK `(igsid, day)`, `cost(day, cost_usd)`, `conversions`), single connection with `check_same_thread=False`, writes in transactions.
- [ ] **Step 4: Run → PASS. Step 5: Commit** `"feat: sqlite store for dedup, quota, spend, log"`.

### Task 3: Instagram Graph API client

**Files:**
- Create: `app/ig_client.py`, `tests/test_ig_client.py`

**Interfaces:**
- Consumes: nothing (plain `httpx`).
- Produces: `IGClient(access_token: str, ig_account_id: str, http: httpx.Client)` with:
  - `download_media(url: str) -> bytes` — GET with `access_token` query param, raise `IGError` on non-2xx.
  - `send_text(recipient_id: str, text: str) -> None` — POST `https://graph.instagram.com/v21.0/{ig_account_id}/messages` with JSON `{"recipient": {"id": ...}, "message": {"text": ...}}` and Bearer auth, raise `IGError` on non-2xx.

- [ ] **Step 1: Write failing `tests/test_ig_client.py`** using `respx`: download attaches token param and returns bytes; 4xx → `IGError`; send_text posts the exact recipient/text body with Bearer header; 4xx → `IGError`.
- [ ] **Step 2: Run → FAIL. Step 3: Implement** `app/ig_client.py` (define `class IGError(Exception)` here).
- [ ] **Step 4: Run → PASS. Step 5: Commit** `"feat: instagram graph api client"`.

### Task 4: Reply copy and chunker

**Files:**
- Create: `app/replies.py`, `tests/test_replies.py`

**Interfaces:**
- Consumes: nothing.
- Produces: constants `HINT_TEXT`, `SORRY_TEXT`, `LIMIT_TEXT`, `BUSY_TEXT` and `chunk_recipe(recipe: str, max_chars: int) -> list[str]` (max 2 chunks).

- [ ] **Step 1: Write failing `tests/test_replies.py`**: short recipe → 1 chunk; 5000-char recipe with `## Steg` section → 2 chunks, split on a `\n` boundary, no chunk > `max_chars`, nothing dropped (joined chunks contain every line); chunker falls back to a hard split when no newline split point fits.
- [ ] **Step 2: Run → FAIL. Step 3: Implement `app/replies.py`** with verbatim copy:
  - `HINT_TEXT = "Send me a cooking video as a DM and I'll reply with the full recipe! 🍳 (max 5 videos/day)"`
  - `SORRY_TEXT = "Hmm, I couldn't extract a recipe from that video. Make sure it's a cooking video where the ingredients and steps are shown or said — and try again!"`
  - `LIMIT_TEXT = "You've used your 5 videos for today. Come back tomorrow — or send me a video you really needed. 🍳"`
  - `BUSY_TEXT = "I'm a bit overwhelmed right now (daily budget spent). Try me again tomorrow!"`
  Chunk preference order: split before a `## ` header line, then before a numbered step line (`^\d+\.` / bullet), then any blank line, then hard cut.
- [ ] **Step 4: Run → PASS. Step 5: Commit** `"feat: fixed reply copy and recipe chunker"`.

### Task 5: Gemini recipe extractor

**Files:**
- Create: `app/extractor.py`, `tests/test_extractor.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ExtractResult(recipe: str | None, cost_usd: float, error: str | None)`; `Extractor(api_key: str, client=None)` (client = injected `google-genai` client; default builds real one) with `extract(video: bytes, mime: str) -> ExtractResult` — uploads via Files API, generates with the fixed prompt below, polls file state until ready (10 min ceiling), returns the model's markdown recipe; `error` set and `recipe=None` on any SDK exception/timeout/"No recipe" sentinel.

- [ ] **Step 1: Write failing `tests/test_replies.py`-sibling `tests/test_extractor.py`** with a fake genai client: happy path returns `ExtractResult(recipe=<text>, cost_usd>=0, error=None)`; SDK raising → `recipe=None`, `error` non-empty; model returning `"NO_RECIPE"` → `recipe=None`, `error="no_recipe"`. (Modeling the SDK surface: fakes expose `files.upload(...)` returning an object with `.state`/`.uri`, and `models.generate_content(...)` returning `.candidates[0].content.parts[0].text` plus `.usage_metadata` for cost — wrap in try so unknown shapes fall back to `cost_usd=0.0`.)
- [ ] **Step 2: Run → FAIL. Step 3: Implement `app/extractor.py`**, model `gemini-2.5-flash`, prompt verbatim:

  ```
  You are a recipe extraction engine. Watch and listen to this video.
  Return the complete recipe as markdown:
  ## <dish name>
  ## Ingredienser / Ingredients
  (quantities + unit per line; estimate amounts shown or said, never invent)
  ## Framgangsmåte / Method
  (numbered steps with times and temperatures as shown or said)
  Write in the language spoken in the video; if unclear, write in English.
  If the video is not a cooking video or the recipe cannot be determined,
  respond with exactly: NO_RECIPE
  ```

  Cost: derive from response usage metadata (tokens × published gemini-2.5-flash rates), `0.0` if unavailable.
- [ ] **Step 4: Run → PASS. Step 5: Commit** `"feat: gemini video recipe extractor"`.

### Task 6: Worker pipeline

**Files:**
- Create: `app/worker.py`, `tests/test_worker.py`

**Interfaces:**
- Consumes: `Store` (Task 2), `IGClient` (Task 3), `Extractor`/`ExtractResult` (Task 5), replies/chunker (Task 4), `Settings` (Task 1).
- Produces: `Worker(store, ig, extractor, settings, today=lambda: date-str)` with `handle_event(event: dict) -> None` — parses one webhook `entry.messaging` dict; sends replies via `ig.send_text`; `today` injected for day-boundary tests.

Parsing rule (specify in code comments): `sender.id` = recipient IGSID; `message.mid` = dedup id; video = first attachment with `type` in `("video", "fallback")` having `payload.url` (check `payload.video_url`/`url` fallbacks); anything else in the message = non-video.

- [ ] **Step 1: Write failing `tests/test_worker.py`** with fakes for store/ig/extractor (record `send_text` calls). One test per Review Focus line plus the happy path:
  1. Happy: video msg → download called, extractor called, reply chunks sent in order, `log_conversion("ok")`.
  2. Duplicate `mid` (`mark_seen` False) → no sends, no quota.
  3. Non-video msg → exactly `HINT_TEXT` sent, no quota.
  4. Attachment `payload` reports size > `max_video_mb` (or download returns > bytes limit — use the size check first, then a post-download byte-size re-check; see Step 3 note) → `SORRY_TEXT`, `log_conversion("oversized")`, no quota, no extractor call.
  5. `consume_quota` False → `LIMIT_TEXT`, `log_conversion("quota")`.
  6. `today_cost ≥ daily_spend_cap_usd` → `BUSY_TEXT`, `log_conversion("busy")`, extractor not called.
  7. Extractor error / `NO_RECIPE` → `SORRY_TEXT`, `log_conversion("no_recipe"|"error")`, quota was consumed.
  8. Long recipe → 2 chunks sent in order.
- [ ] **Step 2: Run → FAIL. Step 3: Implement `app/worker.py`** — order of guards: dedup → non-video → size → spend → quota → download → extract → format → send; each guard logs its status. Post-download re-check: if fetched bytes exceed `max_video_mb * 1_048_576`, treat as oversized *without* refunding the just-consumed quota (consume quota after the size guard, before download).
- [ ] **Step 4: Run → PASS. Step 5: Commit** `"feat: worker pipeline with guards, quota, logging"`.

### Task 7: Webhook endpoints and wiring

**Files:**
- Modify: `app/main.py` (replace Task 1 placeholder app), `tests/test_main.py`

**Interfaces:**
- Consumes: `Worker.handle_event` (Task 6), `Settings` (Task 1).
- Produces: `create_app(worker: Worker, settings: Settings) -> FastAPI` with `GET /webhook` and `POST /webhook`; background execution via `fastapi.BackgroundTasks`.

- [ ] **Step 1: Write failing `tests/test_main.py`** (TestClient, fake worker recording calls): GET with valid `hub.mode=subscribe`, `hub.verify_token`, matching `hub.challenge` → 200 echoing challenge; wrong token → 403. POST valid JSON `{"entry": [{"messaging": [<msg>]}]}` with correct `X-Hub-Signature-256` (HMAC-SHA256 of raw body with `app_secret`, `sha256=` prefix) → 200 and `worker.handle_event` called once per messaging dict; bad signature → 401 and not called; worker raising → still 200.
- [ ] **Step 2: Run → FAIL. Step 3: Implement** in `app/main.py`: signature check uses `hmac.compare_digest`; per-messaging dispatch via BackgroundTasks so the response is fast; whole handler wrapped so exceptions never 500 (Meta redelivers on non-2xx and that would mask bugs — log them).
- [ ] **Step 4: Add `tests/test_e2e_fake.py`**: POST a full video-event payload end-to-end through the real app with fake httpx transport for IG endpoints and a fake Extractor → one recipe reply posted (proves wiring across all modules).
- [ ] **Step 5: Run all → PASS. Step 6: Commit** `"feat: webhook endpoints, signature verification, wiring"`

### Task 8: Runbook, deployment config, launch checklist

**Files:**
- Create: `README.md`, `.env.example`, `railway.json` (`{"$schema": "https://railway.app/railway.schema.json", "deploy": {"startCommand": "uvicorn app.main:asgi --host 0.0.0.0 --port ${PORT:-8000}"}}`), `docs/launch-checklist.md`
- Modify: `app/main.py` (add module-level `asgi = create_app(real_worker, settings)` factory section so uvicorn has an entrypoint)

- [ ] **Step 1: Add the uvicorn entrypoint** (`asgi`) in `app/main.py` behind the testable `create_app`; run `uvicorn app.main:asgi` locally with dummy env → `/health` answers. Commit `"feat: asgi entrypoint, env example, deployment config"`.
- [ ] **Step 2: Write `docs/launch-checklist.md`** — verbatim steps, no code: (a) register company + Meta Business Verification; (b) create IG Professional account + Meta app (Instagram Login route), enable `instagram_business_basic` + `instagram_business_manage_messages`, add testers; (c) set webhook fields (`messages`, subscription for the account) and verify token; (d) enable *Settings → Messages and story replies → Message controls → Connected Tools → Allow access to messages*; (e) manual E2E script with a tester account: text DM → hint; 6 video DMs → 5 replies + limit message; (f) deploy Railway + swap webhook URL to production; (g) submit App Review (Advanced Access) with screencast of (e); (h) go public with a demo Reel.
- [ ] **Step 3: Write `README.md`** — what it is, local dev (ngrok-class tunnel + `ngrok` webhook setup), env var table mirroring `Settings`.
- [ ] **Step 4: Full test run** `pytest -v` → all PASS. Commit `"docs: runbook and launch checklist"`.
