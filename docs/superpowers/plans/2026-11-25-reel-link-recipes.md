# Reel-länksstöd — implementeringsplan

Spec: `docs/superpowers/specs/2026-11-25-reel-link-recipes-design.md`
Alla kommandon körs i rotmappen (`uv run pytest`, `uv run python`). Commit efter varje uppgift.

## Uppgift 1 — `app/reels.py`: hitta permalink i meddelanden

Skapa `app/reels.py`:

```python
import re

_PERMALINK = re.compile(
    r"instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)"
)
_SHORT = re.compile(r"instagr\.am/([A-Za-z0-9_-]+)")


def _codes(value):
    """Yield shortcodes from any nested JSON-ish value."""
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
    """First Instagram shortcode in a DM event (text or any attachment), as permalink."""
    for code in _codes(message.get("message") or message):
        return f"https://www.instagram.com/reel/{code}/"
    return None
```

Test `tests/test_reels.py`:
- text-meddelande med `instagram.com/reel/ABC123/` → permalink.
- share-bilaga `{"attachment": {"payload": {"url": "https://www.instagram.com/tv/Xyz/"}}}` → permalink.
- `instagr.am/abc123` → permalink.
- vanligt textmeddelande utan länk, story-mention, `None`.
- `find_reel_link({"message": {...}})` och bar event-encoding båda.
- flera länkar → första.

Kör: `uv run pytest tests/test_reels.py` (RED först, sedan GREEN).
Commit: `Add reel-link extraction from DM payloads`

## Uppgift 2 — oEmbed-upplösning

Lägg till i `app/reels.py`:

```python
OEMBED_URL = "https://www.instagram.com/api/v1/oembed/"


def resolve_media_id(permalink: str, http) -> str | None:
    """media_id for a public post via Instagram's public oEmbed, None on any failure."""
    try:
        r = http.get(OEMBED_URL, params={"url": permalink}, timeout=10.0)
        if r.status_code != 200:
            return None
        mid = r.json().get("media_id")
        return str(mid) if mid else None
    except Exception:
        return None
```

Test (respx): 200 med `{"media_id": "3806735077687302895"}` → str;
404 → None; ogiltig JSON → None; anropet går med `url`-param = permalink.
Commit: `Add oEmbed media-id resolution`

## Uppgift 3 — `IGClient.get_media`

I `app/ig_client.py`,samma mönster som befintliga metoder:

```python
def get_media(self, media_id: str) -> dict | None:
    """Public Content API: media_type/media_url for any public media, None if not readable."""
    r = self._client.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "media_type,media_url,username", "access_token": self._token},
    )
    if r.status_code != 200:
        return None
    return r.json()
```

(GRAPH/`self._client`/`self._token` = befintliga namn i modulen — anpassa.)
Test (respx): 200 → dict; 404 → None; 200 med error-body → None? (Graph
lyckas aldrig med 200+error här; låt 200 gå igenom). Verifiera URL-fältet.
Commit: `Add IGClient.get_media via Public Content API`

## Uppgift 4 — ny svarstext

I `app/replies.py` lägg till:

```python
REEL_UNAVAILABLE_TEXT = (
    "I saw your reel link! Right now I can only watch the video itself "
    "when you attach the file to the DM (forwarded posts and private "
    "accounts I can't read yet). Thanks for testing! 🍳"
)
```
Test i `tests/test_replies.py` att texten finns och ≤ 2000 tecken.
Commit: `Add reel fallback reply text`

## Uppgift 5 — worker-flödet

I `app/worker.py`, efter att `_video_attachment` returnerar None:

```python
if att is None:
    link = find_reel_link(message)
    if link is None:
        reply(HINT_TEXT, "non_video")
        return
    media_id = resolve_media_id(link, self._http)
    media = self._ig.get_media(media_id) if media_id else None
    if not media or media.get("media_type") not in ("VIDEO", "REEL") or not media.get("media_url"):
        reply(REEL_UNAVAILABLE_TEXT, "reel_unavailable")
        return
    url, mime, size = media["media_url"], "video/mp4", None
    # fall further down the existing download/quota/cap path
```

`Worker.__init__` får ett `http`-gränssnitt (valfritt, annars egen
httpx.Client) för oEmbed; `download_media`/`quota`-flödet lämnas orört —
reel-grenen återanvänder det (ingen extra kvota före nedladdning, samma
cap-fattigdom). `GOOGLE…` (inget). Uppdatera worker-testerna:
- share-bilaga med giltig oEmbed + get_media VIDEO + mp4 → recept skickas
  (FakeIG: get_media returnerar media-url; FakeExtractor ger recipe).
- oEmbed 404 → reel_unavailable, ingen kvota.
- get_media None → reel_unavailable.
- VIDEO men url över max_bytes (download kastar IGOversized) → oversized.
Commit: `Extract recipes from forwarded reels and reel links`

## Uppgift 6 — rå-payload-logg

I `create_app` `receive`: efter signaturkontroll, före parsing eller strax
efter `json.loads`:
`logger.info("webhook payload: %.4000s", body.decode("utf-8", "replace"))`
Test i test_webhook: caplog innehåller "webhook payload" vid giltig leverans.
Commit: `Log raw webhook payloads for debugging`

## Uppgift 7 — hela testsviten + push + deploy

1. `uv run pytest -q` — allt grönt.
2. `uv run pytest tests/ -q` räkning rapporteras.
3. `git push https://prmtnow:<token>@github.com/prmtnow/recipebot feature/mvp`
4. Render → Manual Deploy → "Deploy feature/mvp latest commit".
5. Levande test: användaren vidarebefordrar brendan_pang-reelen → förväntat
   svar REEL_UNAVAILABLE_TEXT (Standard Access blockerar ännu),
   Render-loggen visar payload + var kedjan tvinnade av.
6. När App Review godkänts: samma vidarebefordran ger recept — ingen
   kodändring krävs.
