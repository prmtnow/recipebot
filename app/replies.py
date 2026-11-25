import re

# Instagram's hard limit for one text message; replies are sent as a single DM.
MESSAGE_LIMIT = 2000

HINT_TEXT = ("Send me a cooking video as a DM and I'll reply with the full recipe! "
             "🍳 (max 5 videos/day)")
SORRY_TEXT = ("Hmm, I couldn't extract a recipe from that video. Make sure it's a cooking video "
              "where the ingredients and steps are shown or said — and try again!")
LIMIT_TEXT = ("You've used your 5 videos for today. Come back tomorrow — "
              "or send me a video you really needed. 🍳")
BUSY_TEXT = "I'm a bit overwhelmed right now (daily budget spent). Try me again tomorrow!"

_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_BULLETS = {
    "ingredients": ("🧺", ("ingrediens", "ingredient")),
    "method": ("📝", ("framgangsmåte", "method", "steg", "step", "så här", "tillagning")),
}


def _heading_line(text: str, first: bool) -> str:
    """Map a markdown heading to a DM-friendly emoji section header."""
    if first:
        return f"🍳 {text}"
    lowered = text.lower()
    for emoji, keywords in _BULLETS.values():
        if any(k in lowered for k in keywords):
            return f"{emoji} {text}"
    return text  # unknown section: plain, never invent an emoji


def format_recipe(recipe: str, limit: int = MESSAGE_LIMIT) -> str:
    """Turn the extractor's markdown into one clean, plain-text DM message.

    Instagram DMs render no markdown, so headings become emoji headers,
    bullets become •, bold markers are stripped, blank lines are collapsed,
    and anything over the API limit is cut at a line boundary with an ellipsis.
    """
    lines = []
    seen_heading = False
    for raw in recipe.replace("**", "").splitlines():
        line = raw.rstrip()
        m = _HEADING.match(line)
        if m:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(_heading_line(m.group(1).strip(), first=not seen_heading))
            seen_heading = True
            continue
        stripped = line.lstrip()
        if stripped.startswith(("- ", "* ")):
            lines.append("• " + stripped[2:])
        elif not line and (not lines or lines[-1] == ""):
            continue  # collapse runs of blank lines
        else:
            lines.append(line)
    text = "\n".join(lines).strip("\n")
    if len(text) > limit:
        cut = text.rfind("\n", 0, limit - 1)
        text = (text[:cut] if cut > 0 else text[: limit - 1]).rstrip("\n") + "…"
    return text
