import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROMPT = (
    "You are a recipe extraction engine. Watch and listen to this video.\n"
    "Return the complete recipe as markdown:\n"
    "## <dish name>\n"
    "## Ingredienser / Ingredients\n"
    "(quantities + unit per line; estimate amounts shown or said, never invent)\n"
    "## Framgangsmåte / Method\n"
    "(numbered steps with times and temperatures as shown or said)\n"
    "Your answer is sent as one single message in an Instagram DM: keep it "
    "compact (under 1300 characters), no bold, no links, no extra commentary.\n"
    "Write in the language spoken in the video; if unclear, write in English.\n"
    "If the video is not a cooking video or the recipe cannot be determined,\n"
    "respond with exactly: NO_RECIPE"
)

# Conservative flash-tier rates, USD per 1M tokens (2026-11).
# gemini-2.5-flash was retired for new API keys and gemini-3.8-flash has
# persistent 503 demand spikes; default is gemini-3.6-flash
# (GEMINI_MODEL overrides). Rates used only for the spend cap.
INPUT_RATE_PER_M = 0.30
OUTPUT_RATE_PER_M = 2.50  # applies to output AND billed thinking tokens

_FILE_READY_STATES = {"ACTIVE"}
_FILE_WAITING_STATES = {"PROCESSING", "UNSPECIFIED"}


@dataclass(frozen=True)
class ExtractResult:
    recipe: str | None
    cost_usd: float
    error: str | None


class Extractor:
    """Uploads a video to the Gemini Files API and extracts a text recipe."""

    def __init__(self, api_key: str, client=None, model: str = "gemini-3.6-flash",
                 sleep=time.sleep):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client
        self._model = model
        self._sleep = sleep

    def _generate(self, types, file_uri: str, mime: str):
        """Model call with limited retries for transient 503/429 spikes.

        A rejected call bills no tokens, so retrying is free.
        """
        last: Exception | None = None
        for attempt in range(3):
            try:
                return self._client.models.generate_content(
                    model=self._model,
                    contents=[types.Part.from_uri(file_uri=file_uri, mime_type=mime),
                              PROMPT],
                )
            except Exception as exc:
                if not _transient(exc) or attempt == 2:
                    raise
                last = exc
                logger.warning("transient Gemini error, retrying: %s", exc)
                self._sleep(10 * (attempt + 1))
        raise last  # unreachable, keeps type-checkers happy

    def extract(self, video: bytes, mime: str) -> ExtractResult:
        import io

        from google.genai import types
        f = None
        try:
            f = self._client.files.upload(
                file=io.BytesIO(video),
                config=types.UploadFileConfig(display_name="video.mp4", mime_type=mime),
            )
            deadline = time.monotonic() + 600
            while _state(f) in _FILE_WAITING_STATES and time.monotonic() < deadline:
                time.sleep(5)
                f = self._client.files.get(name=f.name)
            if _state(f) not in _FILE_READY_STATES:
                return ExtractResult(None, 0.0, f"file not ready (state {_state(f)})")
            resp = self._generate(types, f.uri, mime)
            # Capture cost immediately: it is spent even if parsing the
            # response shape fails below.
            cost = _cost(getattr(resp, "usage_metadata", None))
        except Exception as exc:  # any SDK/network failure -> apologetic reply upstream
            return ExtractResult(None, 0.0, str(exc) or type(exc).__name__)
        finally:
            if f is not None:
                try:
                    self._client.files.delete(name=f.name)
                except Exception:
                    logger.warning("could not delete Gemini file %s", f.name)
        try:
            text = (resp.candidates[0].content.parts[0].text or "").strip()
        except Exception:
            return ExtractResult(None, cost, "unexpected response shape")
        if not text:
            return ExtractResult(None, cost, "empty response")
        if text == "NO_RECIPE":
            return ExtractResult(None, cost, "no_recipe")
        return ExtractResult(text, cost, None)


def _state(f) -> str:
    s = getattr(f, "state", None)
    return str(getattr(s, "value", s) or "").upper()


def _transient(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in (429, 500, 503):
        return True
    msg = str(exc).upper()
    return any(m in msg for m in ("503", "429", "UNAVAILABLE", "HIGH DEMAND",
                                  "RATE LIMIT"))


def _cost(usage) -> float:
    if usage is None:
        return 0.0
    billed_output = (getattr(usage, "candidates_token_count", 0)
                     + getattr(usage, "thoughts_token_count", 0))
    return (getattr(usage, "prompt_token_count", 0) * INPUT_RATE_PER_M
            + billed_output * OUTPUT_RATE_PER_M) / 1_000_000
