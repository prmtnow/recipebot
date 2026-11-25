import sqlite3

import pytest

from app.config import Settings
from app.extractor import ExtractResult
from app.ig_client import IGOversized
from app.replies import (BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, MESSAGE_LIMIT,
                         REEL_UNAVAILABLE_TEXT, SORRY_TEXT)
from app.store import Store
from app.worker import Worker

DAY = "2026-11-24"
IGSID = "igsid-1"


class FakeIG:
    def __init__(self, video=b"real-video", download_raises=None, media=None):
        self.sent = []
        self.downloads = []
        self.media_lookups = []
        self.video = video
        self.download_raises = download_raises
        self.media = media  # dict returned by get_media, or None

    def download_media(self, url, max_bytes=None):
        self.downloads.append(url)
        if self.download_raises:
            raise self.download_raises
        if max_bytes is not None and len(self.video) > max_bytes:
            raise IGOversized("too big")
        return self.video

    def get_media(self, media_id):
        self.media_lookups.append(media_id)
        return self.media

    def send_text(self, recipient_id, text):
        self.sent.append((recipient_id, text))


class FakeOembedHttp:
    """Stands in for the public oEmbed endpoint used to resolve reel links."""

    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {"media_id": "3806735077687302895"}
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append((url, params))
        outer = self

        class Resp:
            status_code = outer.status

            def json(self):
                if not isinstance(outer.body, dict):
                    raise ValueError("not json")
                return outer.body

        return Resp()


class FakeExtractor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def extract(self, video, mime):
        self.calls.append((video, mime))
        return self.result


def make_settings(**kw):
    base = dict(ig_access_token="t", ig_account_id="a", app_secret="s",
                verify_token="v", gemini_api_key="g", db_path=":memory:",
                max_video_mb=1, daily_user_limit=5, daily_spend_cap_usd=20.0)
    base.update(kw)
    return Settings(**base)


def video_event(length=None):
    payload = {"url": "https://cdn.example/v.mp4",
               "video": {"url": "https://cdn.example/v.mp4", "mime_type": "video/mp4"}}
    if length is not None:
        payload["video"]["length"] = length
    return {"sender": {"id": IGSID},
            "message": {"mid": "m1", "attachments": [{"type": "video", "payload": payload}]}}


def text_event():
    return {"sender": {"id": IGSID}, "message": {"mid": "m1", "text": "hei"}}


def build(tmp_path, ig=None, extractor=None, http=None, **settings_kw):
    store = Store(str(tmp_path / "bot.db"))
    worker = Worker(store, ig or FakeIG(), extractor or FakeExtractor(
        ExtractResult("# Opskrift", 0.1, None)),
        make_settings(**settings_kw), today=lambda: DAY, http=http)
    return store, worker


def statuses(db_path):
    db = sqlite3.connect(db_path)
    return [r[0] for r in db.execute("SELECT status FROM conversions")]


def quota_count(db_path, igsid=IGSID):
    db = sqlite3.connect(db_path)
    row = db.execute("SELECT count FROM quotas WHERE igsid=?", (igsid,)).fetchone()
    return row[0] if row else 0


def test_happy_path_sends_recipe_and_logs(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)
    w.handle_event(video_event())
    assert ig.sent == [(IGSID, "🍳 Opskrift")]
    assert statuses(db) == ["ok"]
    assert quota_count(db) == 1
    assert store.today_cost(DAY) == pytest.approx(0.1)


def test_duplicate_message_is_ignored(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)
    w.handle_event(video_event())
    sent_after_first = list(ig.sent)
    w.handle_event(video_event())
    assert ig.sent == sent_after_first
    assert statuses(db) == ["ok"]


def test_non_video_gets_hint_no_quota(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)
    w.handle_event(text_event())
    assert ig.sent == [(IGSID, HINT_TEXT)]
    assert quota_count(db) == 0
    assert statuses(db) == ["non_video"]


def test_oversized_by_reported_length_before_download(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)
    w.handle_event(video_event(length=2 * 1024 * 1024))  # max_video_mb=1
    assert ig.sent == [(IGSID, SORRY_TEXT)]
    assert ig.downloads == []
    assert quota_count(db) == 0
    assert statuses(db) == ["oversized"]


def test_oversized_by_downloaded_bytes_keeps_quota(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(video=b"x" * (2 * 1024 * 1024))
    store, w = build(tmp_path, ig=ig)
    w.handle_event(video_event())
    assert ig.sent == [(IGSID, SORRY_TEXT)]
    assert quota_count(db) == 1  # consumed: refunding invites size-probe abuse
    assert statuses(db) == ["oversized"]


def test_quota_exhausted_gets_limit_text(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)
    for _ in range(5):
        store.consume_quota(IGSID, DAY, 5)
    w.handle_event(video_event())
    assert ig.sent == [(IGSID, LIMIT_TEXT)]
    assert statuses(db) == ["quota"]


def test_spend_cap_gets_busy_text(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    ex = FakeExtractor(ExtractResult("x", 0.1, None))
    store, w = build(tmp_path, ig=ig, extractor=ex)
    store.add_cost(20.0, DAY)
    w.handle_event(video_event())
    assert ig.sent == [(IGSID, BUSY_TEXT)]
    assert ex.calls == []
    assert statuses(db) == ["busy"]


@pytest.mark.parametrize("error", ["no_recipe", "RuntimeError: boom"])
def test_extraction_failure_sorry_quota_consumed_no_invention(tmp_path, error):
    db = str(tmp_path / "bot.db")
    ig = FakeIG()
    ex = FakeExtractor(ExtractResult(None, 0.05, error))
    store, w = build(tmp_path, ig=ig, extractor=ex)
    w.handle_event(video_event())
    assert ig.sent == [(IGSID, SORRY_TEXT)]
    assert statuses(db) == ["no_recipe" if error == "no_recipe" else "error"]
    assert quota_count(db) == 1


def test_long_recipe_sends_one_truncated_message(tmp_path):
    recipe = "## Ret\n## Steg\n" + "\n".join(f"{i}. trinn nummer {i} med tekst" for i in range(300))
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig, extractor=FakeExtractor(ExtractResult(recipe, 0.1, None)))
    w.handle_event(video_event())
    texts = [t for _, t in ig.sent]
    assert len(texts) == 1
    assert len(texts[0]) <= MESSAGE_LIMIT
    assert texts[0].endswith("…")


def test_send_failure_after_extraction_still_records_cost_and_log(tmp_path):
    """Gemini money is spent whether or not the IG send succeeds."""
    db = str(tmp_path / "bot.db")

    class FailingIG(FakeIG):
        def send_text(self, recipient_id, text):
            raise RuntimeError("IG down")

    store, w = build(tmp_path, ig=FailingIG())
    w.handle_event(video_event())  # must not raise
    assert statuses(db) == ["ok"]
    assert store.today_cost(DAY) == pytest.approx(0.1)


def test_download_failure_gets_sorry_and_error_log(tmp_path):
    """Spec: failures reply with a friendly error, never silence."""
    db = str(tmp_path / "bot.db")
    ig = FakeIG(download_raises=RuntimeError("CDN 404"))
    store, w = build(tmp_path, ig=ig)
    w.handle_event(video_event())  # must not raise
    assert ig.sent == [(IGSID, SORRY_TEXT)]
    assert statuses(db) == ["error"]
    assert quota_count(db) == 1


def test_send_failure_on_guard_reply_does_not_crash(tmp_path):
    ig = FakeIG()
    store, w = build(tmp_path, ig=ig)

    real_send = ig.send_text
    calls = {"n": 0}

    def flaky(recipient, text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("IG down")
        real_send(recipient, text)

    ig.send_text = flaky
    w.handle_event(text_event())  # hint send fails; must not raise


def forwarded_reel_event():
    """Shape captured from the real webhook (2026-11-25): ig_reel attachment
    carries a direct reel_video_id and the caption in `title`."""
    return {"sender": {"id": IGSID}, "message": {
        "mid": "m1",
        "attachments": [{"type": "ig_reel", "payload": {
            "reel_video_id": "18071458121310205",
            "url": "https://www.instagram.com/reel/DX8u27dy3aQ/",
            "title": "GINGER & SPRING ONION POACHED CHICKEN ..."}}]}}


def pasted_link_event(url="https://www.instagram.com/reel/ABC123/"):
    return {"sender": {"id": IGSID}, "message": {"mid": "m1", "text": f"titta {url}"}}


REEL_MEDIA = {"media_type": "VIDEO", "media_url": "https://cdn.example/reel.mp4",
              "username": "brendan_pang"}


def test_forwarded_reel_prefers_permalink_via_oembed(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=REEL_MEDIA)
    http = FakeOembedHttp()
    store, w = build(tmp_path, ig=ig, http=http)
    w.handle_event(forwarded_reel_event())
    assert http.urls[0][1] == {"url": "https://www.instagram.com/reel/DX8u27dy3aQ/"}
    assert ig.media_lookups == ["3806735077687302895"]  # canonical id from oEmbed
    assert ig.downloads == ["https://cdn.example/reel.mp4"]
    assert ig.sent == [(IGSID, "🍳 Opskrift")]
    assert statuses(db) == ["ok"]
    assert quota_count(db) == 1


def test_forwarded_reel_without_url_falls_back_to_payload_id(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=REEL_MEDIA)
    http = FakeOembedHttp()
    store, w = build(tmp_path, ig=ig, http=http)
    w.handle_event({"sender": {"id": IGSID}, "message": {
        "mid": "m1", "attachments": [{"type": "ig_reel", "payload": {
            "reel_video_id": "18071458121310205"}}]}})
    assert http.urls == []  # no permalink in this payload shape
    assert ig.media_lookups == ["18071458121310205"]
    assert statuses(db) == ["ok"]


def test_forwarded_reel_survives_oembed_outage(tmp_path):
    """Permalink lookup down -> the payload's own id still gets us through."""
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=REEL_MEDIA)
    store, w = build(tmp_path, ig=ig, http=FakeOembedHttp(status=500, body="boom"))
    w.handle_event(forwarded_reel_event())
    assert ig.media_lookups == ["18071458121310205"]
    assert statuses(db) == ["ok"]


def test_pasted_reel_link_resolves_via_oembed(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=REEL_MEDIA)
    http = FakeOembedHttp()
    store, w = build(tmp_path, ig=ig, http=http)
    w.handle_event(pasted_link_event())
    assert http.urls[0][1] == {"url": "https://www.instagram.com/reel/ABC123/"}
    assert ig.media_lookups == ["3806735077687302895"]
    assert ig.sent == [(IGSID, "🍳 Opskrift")]
    assert statuses(db) == ["ok"]


def test_reel_oembed_failure_gets_fallback_no_quota(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=REEL_MEDIA)
    store, w = build(tmp_path, ig=ig, http=FakeOembedHttp(status=404, body="nope"))
    w.handle_event(pasted_link_event())
    assert ig.sent == [(IGSID, REEL_UNAVAILABLE_TEXT)]
    assert ig.media_lookups == []
    assert quota_count(db) == 0
    assert statuses(db) == ["reel_unavailable"]


def test_reel_unreadable_media_gets_fallback(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media=None)  # private account / Standard Access / deleted post
    store, w = build(tmp_path, ig=ig, http=FakeOembedHttp())
    w.handle_event(forwarded_reel_event())
    assert ig.sent == [(IGSID, REEL_UNAVAILABLE_TEXT)]
    assert statuses(db) == ["reel_unavailable"]


def test_reel_image_post_gets_fallback(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(media={"media_type": "IMAGE", "media_url": "https://cdn.example/i.jpg"})
    store, w = build(tmp_path, ig=ig, http=FakeOembedHttp())
    w.handle_event(forwarded_reel_event())
    assert ig.sent == [(IGSID, REEL_UNAVAILABLE_TEXT)]
    assert statuses(db) == ["reel_unavailable"]


def test_reel_oversized_keeps_quota(tmp_path):
    db = str(tmp_path / "bot.db")
    ig = FakeIG(video=b"x" * (2 * 1024 * 1024), media=REEL_MEDIA)
    store, w = build(tmp_path, ig=ig, http=FakeOembedHttp())  # max_video_mb=1
    w.handle_event(forwarded_reel_event())
    assert ig.sent == [(IGSID, SORRY_TEXT)]
    assert statuses(db) == ["oversized"]
    assert quota_count(db) == 1
