import hashlib
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.worker import Worker

logger = logging.getLogger(__name__)


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
            extractor = Extractor(settings.gemini_api_key)
        return settings, store, ig, extractor

    @app.get("/health")
    def health():
        return {"status": "ok"}

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
