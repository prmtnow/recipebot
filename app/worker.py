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

    def _reel_play_url(self, media_ids) -> str | None:
        """Playable URL for the first candidate media id Graph can read.
        (DM payload ids and oEmbed ids live in different id spaces, and under
        Standard Access we cannot tell in advance which one the API accepts.)
        """
        for media_id in media_ids:
            media = self._ig.get_media(media_id) if media_id else None
            if media and media.get("media_type") in ("VIDEO", "REEL"):
                return media.get("media_url")
        return None

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
            # A reel reference arrives either as a media id inside a forwarded
            # ig_reel attachment, and/or as a permalink (in the text or in the
            # attachment's url field). The two ids name the same reel in
            # different id spaces, so offer every candidate to the Graph API.
            candidates = []
            payload_id = find_media_id(msg)
            if payload_id:
                candidates.append(payload_id)
            link = find_reel_link(msg)
            if link is None and not candidates:
                reply(HINT_TEXT, "non_video")
                return
            if link is not None:
                oembed_id = self._oembed_media_id(link)
                if oembed_id and oembed_id not in candidates:
                    candidates.append(oembed_id)
            url = self._reel_play_url(candidates)
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
