import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.extractor import ExtractResult
from app.store import Store
from app.main import create_app

DAY = "2026-11-24"
SECRET = "s"
VERIFY = "v"


class FakeIG:
    def __init__(self, video=b"real-video"):
        self.sent = []
        self.video = video

    def download_media(self, url, max_bytes=None):
        return self.video

    def send_text(self, recipient_id, text):
        self.sent.append((recipient_id, text))


class FakeExtractor:
    def __init__(self, result):
        self.result = result

    def extract(self, video, mime):
        return self.result


def make_app(tmp_path, extractor=None):
    settings = Settings(ig_access_token="t", ig_account_id="a", app_secret=SECRET,
                        verify_token=VERIFY, gemini_api_key="g",
                        db_path=str(tmp_path / "bot.db"))
    store = Store(str(tmp_path / "bot.db"))
    ig = FakeIG()
    app = create_app(settings, store, ig,
                     extractor or FakeExtractor(ExtractResult("# Brød\n1. Bland deig", 0.12, None)),
                     today=lambda: DAY)
    return TestClient(app), ig, store


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def video_payload(mid="m1", sender="igsid-1"):
    return {"object": "instagram", "entry": [{
        "id": "IG-1",
        "messaging": [{
            "sender": {"id": sender},
            "recipient": {"id": "act-1"},
            "timestamp": 1700000000000,
            "message": {"mid": mid, "attachments": [{
                "type": "video",
                "payload": {"url": "https://cdn.example/v.mp4",
                            "video": {"url": "https://cdn.example/v.mp4",
                                      "mime_type": "video/mp4"}}}],
                        },
        }],
    }]}


def test_get_validates_verify_token(tmp_path):
    client, _, _ = make_app(tmp_path)
    ok = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.challenge": "12345", "hub.verify_token": VERIFY})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.challenge": "12345", "hub.verify_token": "wrong"})
    assert bad.status_code == 403


def test_post_rejects_bad_signature(tmp_path):
    client, _, _ = make_app(tmp_path)
    body = json.dumps(video_payload()).encode()
    resp = client.post("/webhook", content=body,
                       headers={"X-Hub-Signature-256": "sha256=deadbeef",
                                "Content-Type": "application/json"})
    assert resp.status_code == 403


def test_post_valid_signature_processes_event(tmp_path):
    client, ig, store = make_app(tmp_path)
    body = json.dumps(video_payload()).encode()
    resp = client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": sign(body), "Content-Type": "application/json"})
    assert resp.status_code == 200
    assert ig.sent == [("igsid-1", "# Brød\n1. Bland deig")]
    assert store.today_cost(DAY) > 0


def test_duplicate_delivery_ignored_end_to_end(tmp_path):
    client, ig, _ = make_app(tmp_path)
    body = json.dumps(video_payload(mid="dup")).encode()
    headers = {"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"}
    client.post("/webhook", content=body, headers=headers)
    resp = client.post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200
    assert len(ig.sent) == 1


def test_no_recipe_gets_apology_end_to_end(tmp_path):
    client, ig, _ = make_app(
        tmp_path, extractor=FakeExtractor(ExtractResult(None, 0.05, "no_recipe")))
    body = json.dumps(video_payload()).encode()
    client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": sign(body), "Content-Type": "application/json"})
    assert len(ig.sent) == 1
    assert "couldn't extract" in ig.sent[0][1]


def test_webhook_returns_200_even_when_processing_fails(tmp_path):
    """Meta must never be asked to redeliver; failures are logged, not thrown."""

    class BrokenIG(FakeIG):
        def download_media(self, url, max_bytes=None):
            raise RuntimeError("CDN on fire")

    settings = Settings(ig_access_token="t", ig_account_id="a", app_secret=SECRET,
                        verify_token=VERIFY, gemini_api_key="g",
                        db_path=str(tmp_path / "bot.db"))
    store = Store(str(tmp_path / "bot.db"))
    app = create_app(settings, store, BrokenIG(),
                     FakeExtractor(ExtractResult("# R", 0.1, None)), today=lambda: DAY)
    client = TestClient(app, raise_server_exceptions=False)
    body = json.dumps(video_payload()).encode()
    resp = client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": sign(body), "Content-Type": "application/json"})
    assert resp.status_code == 200
