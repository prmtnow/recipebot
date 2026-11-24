import hashlib
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.worker import Worker

logger = logging.getLogger(__name__)

PRIVACY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RecipeBot – Privacy Policy</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto;
         padding: 0 20px; line-height: 1.6; color: #222; }
  h1 { font-size: 1.6rem; } h2 { font-size: 1.15rem; margin-top: 1.6em; }
  footer { margin-top: 3em; font-size: 0.85rem; color: #666; }
</style>
</head>
<body>
<h1>RecipeBot Privacy Policy</h1>
<p>Last updated: 2026-11-24</p>
<p>RecipeBot (the “Service”) replies to your Instagram direct messages with a
text recipe extracted from cooking videos you send us. This policy explains
what we collect and how we use it.</p>

<h2>What we collect</h2>
<ul>
  <li>The video file you send us in an Instagram direct message.</li>
  <li>Your Instagram user ID, needed to send the reply back to you.</li>
  <li>The text recipe we generate for you.</li>
</ul>

<h2>How we use it</h2>
<p>We send the video you provide to Google Gemini, an AI service, which
transcribes and summarizes it into a recipe. We use the result for nothing
else than replying to you. We do not sell your data and we do not use it for
advertising.</p>

<h2>Data retention</h2>
<p>Video files are processed in memory and not stored on our servers. We keep
a small record of which messages we have already processed so that we can
avoid duplicate replies, and a daily counter used to apply usage limits.</p>

<h2>Your rights</h2>
<p>You can stop using the Service at any time by simply not sending videos.
To request deletion of the records we keep about you, contact us below.</p>

<h2>Contact</h2>
<p>RecipeBot is operated by Handelsbolaget Molander &amp; Dahl,
Fersens Väg 20, 211 42 Malmö, Sweden.<br>
E-mail: <a href="mailto:torvie@gmail.com">torvie@gmail.com</a></p>

<footer>Handelsbolaget Molander &amp; Dahl · Fersens Väg 20, 211 42 Malmö</footer>
</body>
</html>
"""


def _signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + digest, header)


def _safe_handle(worker: Worker, event: dict) -> None:
    """Background task body: never let an exception escape unlogged."""
    try:
        worker.handle_event(event)
    except Exception:
        logger.exception("failed handling messaging event %s",
                         event.get("message", {}).get("mid", "?"))


def create_app(settings=None, store=None, ig=None, extractor=None, today=None) -> FastAPI:
    app = FastAPI(title="Instagram Recipe Bot")

    def deps():
        """Build the wiring lazily so /health works without configuration."""
        nonlocal settings, store, ig, extractor
        if settings is None:
            from app.config import Settings
            settings = Settings.from_env()
        if store is None:
            from app.store import Store
            store = Store(settings.db_path)
        if ig is None:
            import httpx

            from app.ig_client import IGClient
            ig = IGClient(settings.ig_access_token, settings.ig_account_id,
                          httpx.Client(timeout=httpx.Timeout(120.0, read=120.0)))
        if extractor is None:
            from app.extractor import Extractor
            extractor = Extractor(settings.gemini_api_key, model=settings.gemini_model)
        return settings, store, ig, extractor

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy():
        """Public privacy policy page (required by Meta App Review)."""
        return PRIVACY_HTML

    @app.get("/webhook")
    def verify(mode: str = Query("", alias="hub.mode"),
               challenge: str = Query("", alias="hub.challenge"),
               verify_token: str = Query("", alias="hub.verify_token")):
        s, *_ = deps()
        if mode == "subscribe" and verify_token == s.verify_token:
            return PlainTextResponse(challenge)
        return PlainTextResponse("forbidden", status_code=403)

    @app.post("/webhook")
    async def receive(request: Request, background_tasks: BackgroundTasks):
        """Ack immediately; extract in the background.

        Extraction takes tens of seconds (download + Gemini), well past Meta's
        respond-or-retry window. BackgroundTasks run after the response is
        sent, and dedup makes any redelivery harmless.
        """
        s, store_, ig_, extractor_ = deps()
        body = await request.body()
        if not _signature_ok(s.app_secret, body,
                             request.headers.get("X-Hub-Signature-256")):
            return PlainTextResponse("forbidden", status_code=403)
        try:
            payload = json.loads(body)
        except ValueError:
            return Response(status_code=200)
        worker = Worker(store_, ig_, extractor_, s, today=today)
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                message = event.get("message")
                if not message or message.get("is_echo") or "echo" in message:
                    continue
                background_tasks.add_task(_safe_handle, worker, event)
        return Response(status_code=200)

    return app
