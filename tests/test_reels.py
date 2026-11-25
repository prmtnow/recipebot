import httpx
import pytest
import respx

from app.reels import OEMBED_URL, find_reel_link, resolve_media_id


def event_with(message: dict) -> dict:
    return {"sender": {"id": "u1"}, "message": message}


def test_permalink_in_plain_text():
    ev = event_with({"mid": "m1", "text": "kolla den här: https://www.instagram.com/reel/ABC123/!"})
    assert find_reel_link(ev["message"]) == "https://www.instagram.com/reel/ABC123/"


def test_forwarded_reel_share_attachment():
    msg = {"mid": "m1", "attachments": [{"type": "share",
                                         "payload": {"url": "https://www.instagram.com/reel/Xyz-9/"}}]}
    assert find_reel_link(msg) == "https://www.instagram.com/reel/Xyz-9/"


def test_ig_post_attachment_canonical_url():
    msg = {"mid": "m1", "text": "titta", "attachments": [
        {"type": "ig_post", "payload": {"canonical_url": "https://www.instagram.com/p/Qw8ErT/"}}]}
    assert find_reel_link(msg) == "https://www.instagram.com/reel/Qw8ErT/"


def test_short_domain_and_tv_paths():
    assert find_reel_link({"text": "https://instagr.am/abc123"}) == "https://www.instagram.com/reel/abc123/"
    assert find_reel_link({"text": "https://www.instagram.com/tv/TV123"}) == "https://www.instagram.com/reel/TV123/"


def test_no_link_returns_none():
    assert find_reel_link({"mid": "m1", "text": "hej på dej"}) is None
    assert find_reel_link({"mid": "m1", "attachments": [
        {"type": "story_mention", "payload": {"story_url": "https://example.com/"}}]}) is None
    assert find_reel_link({}) is None


def test_multiple_links_first_wins():
    msg = {"text": "https://www.instagram.com/reel/AAA/ och https://www.instagram.com/reel/BBB/"}
    assert find_reel_link(msg) == "https://www.instagram.com/reel/AAA/"


@respx.mock
def test_resolve_media_id_from_oembed():
    route = respx.get(OEMBED_URL).mock(return_value=httpx.Response(
        200, json={"media_id": "3806735077687302895", "title": "x"}))
    assert resolve_media_id("https://www.instagram.com/reel/ABC/", httpx.Client()) == "3806735077687302895"
    assert route.calls.last.request.url.params["url"] == "https://www.instagram.com/reel/ABC/"


@respx.mock
@pytest.mark.parametrize("response", [
    httpx.Response(404, text="nope"),
    httpx.Response(200, text="not json"),
    httpx.Response(200, json={"title": "no media id"}),
])
def test_resolve_media_id_failures_return_none(response):
    respx.get(OEMBED_URL).mock(return_value=response)
    assert resolve_media_id("https://www.instagram.com/reel/ABC/", httpx.Client()) is None
