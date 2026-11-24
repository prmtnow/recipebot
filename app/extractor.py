import time
from dataclasses import dataclass

PROMPT = (
    "You are a recipe extraction engine. Watch and listen to this video.\n"
    "Return the complete recipe as markdown:\n"
    "## <dish name>\n"
    "## Ingredienser / Ingredients\n"
    "(quantities + unit per line; estimate amounts shown or said, never invent)\n"
    "## Framgangsmåte / Method\n"
    "(numbered steps with times and temperatures as shown or said)\n"
    "Write in the language spoken in the video; if unclear, write in English.\n"
    "If the video is not a cooking video or the recipe cannot be determined,\n"
    "respond with exactly: NO_RECIPE"
)

# Published gemini-2.5-flash rates, USD per 1M tokens (2026-11).
INPUT_RATE_PER_M = 0.30
OUTPUT_RATE_PER_M = 2.50

_FILE_READY_STATES = {"ACTIVE"}
_FILE_WAITING_STATES = {"PROCESSING", "UNSPECIFIED", ""}


@dataclass(frozen=True)
class ExtractResult:
    recipe: str | None
    cost_usd: float
    error: str | None


class Extractor:
    """Uploads a video to the Gemini Files API and extracts a text recipe."""

    def __init__(self, api_key: str, client=None):
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        self._client = client

    def extract(self, video: bytes, mime: str) -> ExtractResult:
        from google.genai import types
        try:
            f = self._client.files.upload(file=("video.mp4", video, mime))
            deadline = time.monotonic() + 600
            while _state(f) in _FILE_WAITING_STATES and time.monotonic() < deadline:
                time.sleep(5)
                f = self._client.files.get(name=f.name)
            if _state(f) not in _FILE_READY_STATES:
                return ExtractResult(None, 0.0, f"file not ready (state {_state(f)})")
            resp = self._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[types.Part.from_uri(file_uri=f.uri, mime_type=mime), PROMPT],
            )
            cost = _cost(getattr(resp, "usage_metadata", None))
            text = (resp.candidates[0].content.parts[0].text or "").strip()
            if text == "NO_RECIPE":
                return ExtractResult(None, cost, "no_recipe")
            return ExtractResult(text, cost, None)
        except Exception as exc:  # any SDK/network failure -> apologetic reply upstream
            return ExtractResult(None, 0.0, str(exc) or type(exc).__name__)


def _state(f) -> str:
    s = getattr(f, "state", None)
    return str(getattr(s, "value", s) or "").upper()


def _cost(usage) -> float:
    if usage is None:
        return 0.0
    return (getattr(usage, "prompt_token_count", 0) * INPUT_RATE_PER_M
            + getattr(usage, "candidates_token_count", 0) * OUTPUT_RATE_PER_M) / 1_000_000
