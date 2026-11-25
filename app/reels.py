"""Find and resolve Instagram reel links inside DM payloads.

A forwarded reel or a pasted instagram.com link carries no video file, only a
reference to the original post. These helpers recover the permalink and resolve
it to a media id via Instagram's public (no-auth) oEmbed endpoint.
"""

import re

OEMBED_URL = "https://www.instagram.com/api/v1/oembed/"

_PERMALINK = re.compile(r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)")
_SHORT = re.compile(r"instagr\.am/([A-Za-z0-9_-]+)")


def _codes(value):
    """Yield shortcodes found anywhere in a nested JSON-ish value."""
    if isinstance(value, str):
        for rx in (_PERMALINK, _SHORT):
            yield from rx.findall(value)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _codes(v)
    elif isinstance(value, list):
        for v in value:
            yield from _codes(v)


def find_reel_link(message: dict) -> str | None:
    """First Instagram post shortcode in a DM message dict, as a reel permalink."""
    for code in _codes(message):
        return f"https://www.instagram.com/reel/{code}/"
    return None


def resolve_media_id(permalink: str, http, timeout: float = 10.0) -> str | None:
    """media_id for a public post via oEmbed, or None on any failure."""
    try:
        resp = http.get(OEMBED_URL, params={"url": permalink}, timeout=timeout)
        if resp.status_code // 100 != 2:
            return None
        media_id = resp.json().get("media_id")
        return str(media_id) if media_id else None
    except Exception:
        return None
