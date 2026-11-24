# Instagram Recipe Bot — MVP Design

Date: 2026-11-24 · Status: awaiting approval

## Intent and why

Fredrik wants to grow a business around an Instagram service that turns cooking
videos into complete text recipes. The agreed business shape is **A: a consumer
brand** — one public Instagram account that people DM videos to. The MVP's job
is to try the loop with real users as cheaply as possible and learn whether
people actually send videos and come back. The B2B evolution (serving many
creators' accounts) is a later phase, but the architecture keeps "account" as a
dimension so that pivot stays open.

## Goals (MVP)

- DM a cooking video file to the bot account → receive a complete text recipe
  (ingredients with quantities, steps, timings) within ~1–2 minutes.
- Works for videos in any language: the recipe is returned in the language
  spoken in the video, English fallback.
- Survive real-world mess: non-cooking videos and failures get a friendly
  reply, never silence.
- Cap: 5 videos per user per day (abuse protection, and it probes where the
  future freemium line sits).

## Non-goals (MVP)

- Reel-link input (unofficial-download gray zone → phase 2).
- Comment-triggered private replies (growth feature → phase 2).
- Payments/subscriptions (proof of demand first).
- Multi-tenant / other businesses' accounts (the B2B phase).

## Anti-goals

- A bot that confidently invents ingredients — better to say "I couldn't
  extract the recipe" than to hallucinate quantities.
- Building a dashboard/admin UI before anyone has DM'd a video.

## Constraints

- Instagram Professional account required for the Messaging API.
- During development, Meta app **Standard Access** suffices (testers with
  roles on the app). Messaging the public requires **Advanced Access**, i.e.
  App Review + Business Verification with a registered company — the longest
  lead-time item; apply early, in parallel with the build.
- Messaging limits are generous (100 text msgs/sec); the real cost driver is
  AI inference (~$0.05–0.30/video).
- Replies must arrive within Meta's messaging window (24h) — the loop takes
  minutes, so no risk.

## Approaches considered

1. **Consumer account, DM-in/recipe-out (chosen).** Cheapest to launch, the
   bot doubles as its own marketing. Trade-off: Fredrik pays inference for
   all usage, so caps are needed.
2. **B2B SaaS for creators.** Predictable revenue, API-first fit, but a
   harder first sale and premature until extraction quality is proven.
3. **Links-only input.** Best UX, but the core product would depend on an
   unofficial downloader; rejected as MVP risk.

Chosen: 1, built so 2 can grow out of it.

## How it works

- **IG account**: new Professional (business) account + Meta app
  (Instagram Login route: `instagram_business_basic`,
  `instagram_business_manage_messages`; no Facebook Page required).
- **Server**: Python + FastAPI, single service.
  1. Webhook receives `messages` events (verify token, handle redeliveries
     idempotently by message ID).
  2. Video attachment → download via the media URL using the access token
     (size/duration guard before download).
  3. Upload to Gemini (Files API), run a recipe-extraction prompt with video
     support; get structured text back; format as a clean recipe message,
     splitting into two messages if very long.
  4. Reply via Send API; on failure, reply with a friendly error.
- **State**: SQLite — per-user daily counters, processed-message IDs, a log
  of every video→recipe pair (this log is the learning asset: where it fails,
  which cuisines, what users ask).
- **Deploy**: small instance on Railway or Fly.io; HTTPS + public URL
  required for webhooks. During local development, an ngrok-class tunnel.
- **Cost guard**: hard daily global spend cap on inference.

## Left to the builder

- Exact Gemini model and prompt tuning.
- Recipe message formatting (emoji, headers, length tuning).
- Welcome message / quick-reply setup in the IG inbox.
- Webhook event dedup details, retry policy.

## Milestones

1. Skeleton service + webhook echoing "got your video" (Standard Access testers).
2. Video → Gemini → recipe reply working end-to-end for testers.
3. Caps, error handling, logging.
4. Submit App Review + Business Verification; go public with a demo Reel.
