import httpx
import pytest
import respx

from app.ig_client import IGClient, IGOversized, IGError

MSG_URL = "https://graph.facebook.com/v23.0/act-1/messages"


@respx.mock
def test_download_media_attaches_token_and_returns_bytes():
    route = respx.get("https://cdn.example/v.mp4").mock(
        return_value=httpx.Response(200, content=b"vid"))
    with httpx.Client() as http:
        data = IGClient("tok", "act-1", http).download_media("https://cdn.example/v.mp4")
    assert data == b"vid"
    query = httpx.QueryParams(route.calls.last.request.url.query)
    assert query["access_token"] == "tok"


@respx.mock
def test_download_media_raises_on_error_status():
    respx.get("https://cdn.example/v.mp4").mock(return_value=httpx.Response(400))
    with httpx.Client() as http:
        with pytest.raises(IGError):
            IGClient("tok", "act-1", http).download_media("https://cdn.example/v.mp4")


@respx.mock
def test_send_text_posts_exact_body_and_bearer_auth():
    route = respx.post(MSG_URL).mock(return_value=httpx.Response(200, json={"ok": True}))
    with httpx.Client() as http:
        IGClient("tok", "act-1", http).send_text("igsid-9", "Recipe!")
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    import json
    assert json.loads(req.content) == {
        "recipient": {"id": "igsid-9"},
        "message": {"text": "Recipe!"},
    }


@respx.mock
def test_send_text_raises_on_error_status():
    respx.post(MSG_URL).mock(return_value=httpx.Response(429))
    with httpx.Client() as http:
        with pytest.raises(IGError):
            IGClient("tok", "act-1", http).send_text("igsid-9", "hi")


@respx.mock
def test_download_media_aborts_when_body_exceeds_cap():
    respx.get("https://cdn.example/big.mp4").mock(
        return_value=httpx.Response(200, content=b"x" * 5000))
    with httpx.Client() as http:
        with pytest.raises(IGOversized):
            IGClient("tok", "act-1", http).download_media(
                "https://cdn.example/big.mp4", max_bytes=1000)


@respx.mock
def test_download_media_within_cap_returns_bytes():
    respx.get("https://cdn.example/v.mp4").mock(
        return_value=httpx.Response(200, content=b"vid"))
    with httpx.Client() as http:
        data = IGClient("tok", "act-1", http).download_media(
            "https://cdn.example/v.mp4", max_bytes=1000)
    assert data == b"vid"

MEDIA_URL = "https://graph.facebook.com/v23.0/3806735077687302895"


@respx.mock
def test_get_media_returns_json_with_fields_and_token():
    route = respx.get(MEDIA_URL).mock(return_value=httpx.Response(
        200, json={"media_type": "VIDEO", "media_url": "https://cdn.example/r.mp4"}))
    with httpx.Client() as http:
        media = IGClient("tok", "act-1", http).get_media("3806735077687302895")
    assert media["media_type"] == "VIDEO"
    query = httpx.QueryParams(route.calls.last.request.url.query)
    assert query["fields"] == "media_type,media_url,username"
    assert query["access_token"] == "tok"


@respx.mock
def test_get_media_returns_none_when_unreadable():
    respx.get(MEDIA_URL).mock(return_value=httpx.Response(400, json={
        "error": {"message": "Unsupported get request.", "code": 100}}))
    with httpx.Client() as http:
        assert IGClient("tok", "act-1", http).get_media("3806735077687302895") is None
