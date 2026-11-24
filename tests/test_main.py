from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_privacy_page_served():
    client = TestClient(create_app())
    resp = client.get("/privacy")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "RecipeBot" in resp.text
    # Meta requires a visible contact address
    assert "torvie@gmail.com" in resp.text
