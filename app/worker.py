import logging
from datetime import date

from app.ig_client import IGOversized
from app.reels import find_media_id, find_reel_link, resolve_media_id
from app.replies import (BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, REEL_UNAVAILABLE_TEXT,
                         SORRY_TEXT, format_recipe)

logger = logging.getLogger(__name__)


def _video_attachment(message: dict):
    """First video-ish attachment: (url, mime, size_bytes|None) or None."""
    for att in message.get("attachments") or []:
        if att.get("type") not in ("video", "fallback"):
            continue
        payload = att.get("payload") or {}
        video = payload.get("video") or {}
        url = video.get("url") or payload.get("url")
        if not url:
            continue
        mime = video.get("mime_type") or payload.get("mime_type") or "video/mp4"
        size = video.get("length") or payload.get("length")
        return url, mime, size
    return None


class Worker:
    """One DM event in, at most one recipe (or honest failure) out."""

    def __init__(self, store, ig, extractor, settings, today=None, http=None):
        self._store = store
        self._ig = ig
        self._extractor = extractor
        self._settings = settings
        self._today = today or (lambda: date.today().isoformat())
        self._http = http  # for public oEmbed lookups; created lazily

    def _oembed_media_id(self, link: str) -> str | None:
        """Resolve a pasted permalink to a media id via public oEmbed."""
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=15.0)
        return resolve_media_id(link, self._http)

    def _reel_play_url(self, media_id: str | None) -> str | None:
        """Playable URL for a reel media id, or None when it can't be read."""
        if media_id is None:
            return None
        media = self._ig.get_media(media_id)
        if not media or media.get("media_type") not in ("VIDEO", "REEL"):
            return None
        return media.get("media_url")

    def handle_event(self, message: dict) -> None:
        store, settings = self._store, self._settings
        igsid = message["sender"]["id"]
        msg = message["message"]
        mid = msg.get("mid", "")
        day = self._today()

        def record(status, recipe=None, cost=0.0):
            logger.info("conversion %s for %s (cost %.4f)", status, igsid, cost)
            if cost:
                store.add_cost(cost, day)
            store.log_conversion(igsid, mid, status, recipe, cost)

        def send(text):
            try:
                self._ig.send_text(igsid, text)
            except Exception:
                logger.exception("reply send failed for %s", igsid)

        def reply(text, status, cost=0.0):
            record(status, cost=cost)  # bookkeeping first: spend is real even if IG is down
            send(text)

        if mid and not store.mark_seen(mid):
            return  # webhook redelivery

        att = _video_attachment(msg)
        if att is None:
            # A reel reference comes either as a permalink (pasted link, or the
            # url inside a forwarded ig_reel attachment) or as a bare media id
            # in the payload. The permalink goes through the verified public
            # oEmbed lookup; the payload's own id (reel_video_id) lives in a
            # different id space and is only a fallback.
            media_id = find_media_id(msg)
            link = find_reel_link(msg)
            if link is None and media_id is None:
                reply(HINT_TEXT, "non_video")
                return
            if link is not None:
                media_id = self._oembed_media_id(link) or media_id
            url = self._reel_play_url(media_id)
            if url is None:
                reply(REEL_UNAVAILABLE_TEXT, "reel_unavailable")
                return
            mime, size = "video/mp4", None  # a reel's size is only known by downloading
        else:
            url, mime, size = att

        max_bytes = settings.max_video_mb * 1_048_576
        if size and size > max_bytes:
            reply(SORRY_TEXT, "oversized")
            return
        if store.today_cost(day) >= settings.daily_spend_cap_usd:
            reply(BUSY_TEXT, "busy")
            return
        if not store.consume_quota(igsid, day, settings.daily_user_limit):
            reply(LIMIT_TEXT, "quota")
            return

        try:
            video = self._ig.download_media(url, max_bytes=max_bytes)
        except IGOversized:
            reply(SORRY_TEXT, "oversized")  # quota stays consumed: no refund-probe abuse
            return
        except Exception:
            logger.exception("media download failed for %s", igsid)
            reply(SORRY_TEXT, "error")
            return

        result = self._extractor.extract(video, mime)
        if result.recipe is None:
            status = "no_recipe" if result.error == "no_recipe" else "error"
            reply(SORRY_TEXT, status, cost=result.cost_usd)
            return

        record("ok", result.recipe, result.cost_usd)  # count spend before sending
        send(format_recipe(result.recipe))
