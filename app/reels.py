"""Find and resolve Instagram reel links inside DM payloads.

A forwarded reel or a pasted instagram.com link carries no video file, only a
reference to the original post. These helpers recover the permalink and resolve
it to a media id via Instagram's public (no-auth) oEmbed endpoint.
"""

import re

# Base for the public (no-auth) oEmbed endpoint. The endpoint needs the
# trailing slash: calling api/v1/oembed (without it) answers with an HTML
# login wall instead of JSON.
OEMBED_ENDPOINT = "https://www.instagram.com/api/v1/oembed/"

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


_ID_KEYS = ("reel_video_id", "video_id", "media_id")


def find_media_id(value) -> str | None:
    """Direct media id from a forwarded-post attachment, as a fallback when
    the permalink oEmbed lookup fails. Note: IG keeps two id spaces; a DM's
    reel_video_id is NOT the same number as the oEmbed media_id for the same
    reel, and only the latter is verified against the Public Content API."""
    if isinstance(value, dict):
        for key in _ID_KEYS:
            if value.get(key):
                return str(value[key])
        for v in value.values():
            found = find_media_id(v)
            if found:
                return found
    elif isinstance(value, list):
        for v in value:
            found = find_media_id(v)
            if found:
                return found
    return None


def resolve_media_id(permalink: str, http, timeout: float = 10.0) -> str | None:
    """media_id for a public post via oEmbed, or None on any failure."""
    try:
        resp = http.get(OEMBED_ENDPOINT, params={"url": permalink}, timeout=timeout)
        if resp.status_code // 100 != 2:
            return None
        media_id = resp.json().get("media_id")
        return str(media_id) if media_id else None
    except Exception:
        return None
