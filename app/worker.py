from datetime import date

from app.replies import BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, MSG_CHUNK_CHARS, SORRY_TEXT, chunk_recipe


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

    def __init__(self, store, ig, extractor, settings, today=None):
        self._store = store
        self._ig = ig
        self._extractor = extractor
        self._settings = settings
        self._today = today or (lambda: date.today().isoformat())

    def handle_event(self, message: dict) -> None:
        store, settings = self._store, self._settings
        igsid = message["sender"]["id"]
        msg = message["message"]
        day = self._today()

        def reply(text, status, recipe=None, cost=0.0):
            if cost:
                store.add_cost(cost, day)
            store.log_conversion(igsid, msg.get("mid", ""), status, recipe, cost)
            self._ig.send_text(igsid, text)

        if not store.mark_seen(msg.get("mid", "")):
            return  # webhook redelivery

        att = _video_attachment(msg)
        if att is None:
            reply(HINT_TEXT, "non_video")
            return
        url, mime, size = att

        if size and size > settings.max_video_mb * 1_048_576:
            reply(SORRY_TEXT, "oversized")
            return
        if store.today_cost(day) >= settings.daily_spend_cap_usd:
            reply(BUSY_TEXT, "busy")
            return
        if not store.consume_quota(igsid, day, settings.daily_user_limit):
            reply(LIMIT_TEXT, "quota")
            return

        video = self._ig.download_media(url)
        if len(video) > settings.max_video_mb * 1_048_576:
            reply(SORRY_TEXT, "oversized")  # quota stays consumed: no refund-probe abuse
            return

        result = self._extractor.extract(video, mime)
        if result.recipe is None:
            status = "no_recipe" if result.error == "no_recipe" else "error"
            reply(SORRY_TEXT, status, cost=result.cost_usd)
            return

        for chunk in chunk_recipe(result.recipe, MSG_CHUNK_CHARS):
            self._ig.send_text(igsid, chunk)
        store.log_conversion(igsid, msg.get("mid", ""), "ok", result.recipe, result.cost_usd)
        if result.cost_usd:
            store.add_cost(result.cost_usd, day)
