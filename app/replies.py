import re

MSG_CHUNK_CHARS = 1800

HINT_TEXT = ("Send me a cooking video as a DM and I'll reply with the full recipe! "
             "🍳 (max 5 videos/day)")
SORRY_TEXT = ("Hmm, I couldn't extract a recipe from that video. Make sure it's a cooking video "
              "where the ingredients and steps are shown or said — and try again!")
LIMIT_TEXT = ("You've used your 5 videos for today. Come back tomorrow — "
              "or send me a video you really needed. 🍳")
BUSY_TEXT = "I'm a bit overwhelmed right now (daily budget spent). Try me again tomorrow!"

# Split preference: before a "## " header, before a numbered/bulleted step,
# before a blank line, then a hard cut.
_SPLIT_PATTERNS = [
    re.compile(r"\n(?=## )"),
    re.compile(r"\n(?=(?:\d+\.|-) )"),
    re.compile(r"\n(?=\n)"),
]


def chunk_recipe(recipe: str, max_chars: int) -> list[str]:
    """Split a recipe into at most 2 messages, never dropping text.

    The first chunk ends at the best boundary within max_chars; the second
    chunk carries the whole remainder even if it exceeds max_chars (a long
    message beats a dropped ingredient list).
    """
    if len(recipe) <= max_chars:
        return [recipe]
    min_cut = len(recipe) - max_chars  # so the second chunk also fits

    def best(pattern: re.Pattern, low: int, high: int):
        candidates = [m.start() for m in pattern.finditer(recipe) if low <= m.start() < high]
        return max(candidates) + 1 if candidates else None  # split after the newline

    cut = None
    for pattern in _SPLIT_PATTERNS:
        cut = best(pattern, min_cut, max_chars)
        if cut:
            break
    if cut is None:  # no boundary lets both chunks fit; keep content priority
        for pattern in _SPLIT_PATTERNS:
            cut = best(pattern, 0, max_chars)
            if cut:
                break
    if cut is None:
        cut = max_chars
    first, rest = recipe[:cut].rstrip("\n"), recipe[cut:].lstrip("\n")
    return [first, rest]
