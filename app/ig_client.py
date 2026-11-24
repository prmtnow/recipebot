import httpx


class IGError(Exception):
    """Any non-2xx response from the Instagram Graph API."""


class IGOversized(IGError):
    """The response body exceeded the configured size cap while streaming."""


class IGClient:
    """Minimal Instagram Graph API client: media download and text replies."""

    def __init__(self, access_token: str, ig_account_id: str, http: httpx.Client):
        self._token = access_token
        self._ig_account_id = ig_account_id
        self._http = http

    def download_media(self, url: str, max_bytes: int | None = None) -> bytes:
        """Stream a media file, aborting as soon as it exceeds max_bytes.

        Meta's reported attachment length can be wrong; streaming keeps the
        worst-case memory use at max_bytes instead of the whole response.
        """
        with self._http.stream("GET", url, params={"access_token": self._token}) as resp:
            if resp.status_code // 100 != 2:
                raise IGError(f"media download failed: {resp.status_code}")
            buf = bytearray()
            for chunk in resp.iter_bytes():
                buf.extend(chunk)
                if max_bytes is not None and len(buf) > max_bytes:
                    raise IGOversized(f"media exceeds {max_bytes} bytes")
            return bytes(buf)

    def send_text(self, recipient_id: str, text: str) -> None:
        resp = self._http.post(
            f"https://graph.instagram.com/v21.0/{self._ig_account_id}/messages",
            headers={"Authorization": f"Bearer {self._token}"},
            json={"recipient": {"id": recipient_id}, "message": {"text": text}},
        )
        if resp.status_code // 100 != 2:
            raise IGError(f"send failed: {resp.status_code} {resp.text[:200]}")
