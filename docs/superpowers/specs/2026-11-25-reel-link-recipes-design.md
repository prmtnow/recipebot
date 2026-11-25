# Reel-länksstöd — design (fas 1.5)

Datum: 2026-11-25 · Status: godkänd av ägaren ("JA")

## Problem

Användaren vill skicka ett recept genom att **vidarebeforda en reel** (eller
klistra in en reel-länk) till @recipegenie.app — utan att först spara videon
till galleriet. Idag svarar boten med HINT_TEXT eftersom en vidarebefordrad
reel inte innehåller någon videobilaga, bara en referens till inlägget.

## Vad vi vet (verifierat 2026-11-25)

1. Vidarebefordrade reels anländer i webhook:en som en bilaga utan
   video-URL i det nuvarande `_video_attachment`-spåret ((Render-loggen
   visade `conversion non_video` för just ett sådant meddelande).
2. Instagrams publia oEmbed-endpoint fungerar utan inloggning/token:
   `GET https://www.instagram.com/api/v1/oembed/?url=https://www.instagram.com/reel/<code>/`
   → JSON med bl.a. `media_id` (verkligt test: brendan_pang-reel →
   `3806735077687302895`).
3. `GET https://graph.facebook.com/v23.0/{media_id}?fields=media_url,media_type,username`
   (Instagram Public Content API, kräver `instagram_basic`) löser media-id
   till nedladdningsbar mp4 via `media_url`. För **andre mans** innehåll
   krävs Advanced Access — med nuvarande Standard Access ser vi bara egna
   media (verkligt test: "missing permissions" på brendan_pang- mediat).
4. Egna/ägda media svarar 200 på samma anrop (test på vår egen publicerade
   bild).

## Design

### Ny modul `app/reels.py`

* `find_reel_link(message: dict) -> str | None`
  — rekursiv genomsökning av meddelandet efter Instagram-permalänkar:
  regex `instagram\.com/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)` och
  `instagr\.am/([A-Za-z0-9_-]+)`, i text **och** i bilagors payload-fält
  (`url`, `canonical_url`, `permalink`). Returnerar första träff som
  fullständig permalink `https://www.instagram.com/reel/<code>/`.
  Fångar därmed både inklistrade länkar och vidarebefordrade reels oavsett
  vilken payload-form Meta använder (`share`, `ig_reel`, `ig_post`, …).
* `resolve_media_id(permalink: str, http: httpx.Client) -> str | None`
  — GET `https://www.instagram.com/api/v1/oembed/?url=…`; returnera
  `media_id` ur JSON:en, `None` vid fel/otillgängligt.

### `IGClient.get_media(media_id) -> dict | None`

GET `graph.facebook.com/v23.0/{media_id}?fields=media_type,media_url,username`
med befintlig SUAT. 404/100 (privat konto, bortaget inlägg, Standard Access)
→ `None`.

### Worker-flöde (nya stegen efter nuvarande `_video_attachment`-misslyckande)

1. `link = find_reel_link(event)`. Ingen → HINT_TEXT (oförändrat).
2. `media_id = resolve_media_id(link)` → annars REEL_UNAVAILABLE_TEXT.
3. `media = ig.get_media(media_id)`; godkänn bara `media_type` i
   {VIDEO, REEL} med `media_url` → annars REEL_UNAVAILABLE_TEXT.
4. Samma skydd som för filer: `max_video_mb`, `daily_spend_cap_usd`,
   `daily_user_limit` (kvota förbrukas först här, precis som idag).
5. Ladd `media_url` → samma Gemini-pipeline. Fri-tal: länkmetoden är
   gratis så long-tar ingen kvota innan nedladdning faktiskt påbörjas.

### Ny svarstext `REEL_UNAVAILABLE_TEXT` (replies.py)

"I saw your reel link! Right now I can only watch the video itself when you
attach the file to the DM (forwarded posts and private accounts I can't read
yet). Thanks for testing! 🍳" (engelska som alla fasta svar)
— ärligt svar medan åtkomsten är Standard. Texten byts till en
succesvariant (ingen extra fråga) när Advanced Access godkänts; för
privna konton förblir den korrekt.

### Loggning

`POST /webhook` loggar payloaden som INFO (avhugget till 4 000 tecken) så
att vidarebefordrade meddelandens exakta form syns i Render-loggen —
underlag för framtida payload-regler.

## Konsekvenser

* **Inga nya permissions** — allt inom de 7 inskickade.
* Innan App Review-godkännande svarar främmande reels med
  REEL_UNAVAILABLE_TEXT (media READ nekas); efter godkännande fungerar
  flödet skarpt utan kodändring.
* Vidarebefordrad reel from **privet** konto → samma oEmbed 404 →
  REEL_UNAVAILABLE_TEXT (korrekt beteende).
* Reels > `max_video_mb` → SORRY_TEXT (som idag).

## Testbarhet

* `find_reel_link`: ren enhet, mata med riktiga payload-former (share/
  ig_post/ig_reel/text).
* `resolve_media_id` / `get_media`: respx med inspelande svar.
* Worker: befintlig FakeIG/FakeExtractor-rykten + en FakeIG med media-route.
