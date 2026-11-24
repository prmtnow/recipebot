import httpx


class IGError(Exception):
    """Any non-2xx response from the Instagram Graph API."""


class IGClient:
    """Minimal Instagram Graph API client: media download and text replies."""

    def __init__(self, access_token: str, ig_account_id: str, http: httpx.Client):
        self._token = access_token
        self._ig_account_id = ig_account_id
        self._http = http

    def download_media(self, url: str) -> bytes:
        resp = self._http.get(url, params={"access_token": self._token})
        if resp.status_code // 100 != 2:
            raise IGError(f"media download failed: {resp.status_code}")
        return resp.content

    def send_text(self, recipient_id: str, text: str) -> None:
        resp = self._http.post(
            f"https://graph.instagram.com/v21.0/{self._ig_account_id}/messages",
            headers={"Authorization": f"Bearer {self._token}"},
            json={"recipient": {"id": recipient_id}, "message": {"text": text}},
        )
        if resp.status_code // 100 != 2:
            raise IGError(f"send failed: {resp.status_code} {resp.text[:200]}")
