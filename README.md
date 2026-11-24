# Instagram Recipe Bot

DM us a cooking video, get back the full recipe. Powered by Gemini video understanding.

## How it works

1. User DMs a cooking video to the Instagram account.
2. Meta pushes a webhook event; the bot validates the signature and dedups.
3. Guards run in order: non-video → size → spend cap → per-user quota.
4. The video is uploaded to the Gemini Files API; `gemini-2.5-flash` extracts the
   recipe as markdown, in the language spoken in the video. No invented recipes:
   if extraction fails, the user gets a friendly apology, never a guess.
5. The recipe is chunked on section/step boundaries and sent back (max 2 messages).

## Run

```bash
pip install -e .
copy .env.example .env   # fill in values
python run.py            # serves /webhook and /health on :8000
```

Deploy anywhere that speaks HTTP (Railway, Fly). Point the Meta app webhook at
`https://<your-host>/webhook` with your `VERIFY_TOKEN`.

## Configuration

See [.env.example](.env.example). Limits: `MAX_VIDEO_MB` (downloads are capped
before extraction), `DAILY_USER_LIMIT` (per user per day), `DAILY_SPEND_CAP_USD`
(global kill switch — the bot goes politely busy when the day's budget is spent).

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

No live Gemini/Instagram calls in tests: HTTP is mocked with respx, the Gemini
client is faked.

## Launch checklist (one-time Meta setup)

The full flow needs Meta **App Review + Business Verification** — start these
early, they take weeks:

- [ ] Register a company (required for Business Verification).
- [ ] Create a [Meta Business Portfolio](https://business.facebook.com) and verify it.
- [ ] Create an Instagram **Professional** (Business) account for the bot.
- [ ] Create an app (type: Business) → add products: *Instagram platform* with
  `instagram_business_basic` and `instagram_business_manage_messages`
  (Instagram Login, i.e. app-managed Instagram accounts — no Facebook Page needed).
- [ ] Generate a long-lived access token for the bot account (App Review tokens
  are long-lived; dev-mode tokens expire hourly — fine while testing).
- [ ] Webhooks: subscribe to `messages` for the account; set callback URL to
  `https://<host>/webhook` and the `VERIFY_TOKEN` you configured.
- [ ] Settings → Message controls → Connected Tools → **Allow access to messages**
  (the classic "webhook never fires" trap).
- [ ] App Review: submit `instagram_business_manage_messages` with a screen
  recording of a DM video → recipe reply (a test account can DM your live bot in
  dev mode to record this).
- [ ] Set the app from Development to Live.

While in development mode the bot only answers DMs from app testers/admins —
perfect for the private beta.

## Deployment notes

Run **one** instance: quotas, the spend cap and dedup live in one SQLite file,
and multi-process writes are not coordinated (fine at MVP volume, a phase-2
item if you ever scale out).

## Status: MVP

MVP = DM'd video files only, one account. Comment triggers, Reel *link* parsing
and B2B multi-account are deliberate phase-2 items (see
[design doc](docs/superpowers/specs/2026-11-24-ig-recipe-bot-mvp-design.md)).
