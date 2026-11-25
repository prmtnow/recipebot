import sqlite3

import pytest

from app.config import Settings
from app.extractor import ExtractResult
from app.ig_client import IGOversized
from app.replies import BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, MESSAGE_LIMIT, SORRY_TEXT
from app.store import Store
from app.worker import Worker

DAY = "2026-11-24"
IGSID = "igsid-1"


class FakeIG:
    def __init__(self, video=b"real-video", download_raises=None):
        self.sent = []
        self.downloads = []
        self.video = video
        self.download_raises = download_raises

    def download_media(self, url, max_bytes=None):
        self.downloads.append(url)
        if self.download_raises:
            raise self.download_raises
        if max_bytes is not None and len(self.video) > max_bytes:
            raise IGOversized("too big")
        return self.video

    def send_text(self, recipient_id, text):
        self.sent.append((recipient_id, text))


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


def build(tmp_path, ig=None, extractor=None, **settings_kw):
    store = Store(str(tmp_path / "bot.db"))
    worker = Worker(store, ig or FakeIG(), extractor or FakeExtractor(
        ExtractResult("# Opskrift", 0.1, None)),
        make_settings(**settings_kw), today=lambda: DAY)
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
