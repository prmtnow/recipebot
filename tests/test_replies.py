from app.replies import BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, MESSAGE_LIMIT, SORRY_TEXT, format_recipe


def test_formats_headings_with_emoji_and_bullets():
    recipe = (
        "## Kaalmaja\n"
        "## Ingredienser / Ingredients\n"
        "- 400 g poached chicken\n"
        "- 300 g rice\n"
        "## Framgangsmåte / Method\n"
        "1. Whisk the dressing.\n"
        "2. Toss and rest."
    )
    assert format_recipe(recipe) == (
        "🍳 Kaalmaja\n"
        "\n"
        "🧺 Ingredienser / Ingredients\n"
        "• 400 g poached chicken\n"
        "• 300 g rice\n"
        "\n"
        "📝 Framgangsmåte / Method\n"
        "1. Whisk the dressing.\n"
        "2. Toss and rest."
    )


def test_strips_bold_markers_and_collapse_blank_lines():
    recipe = "# Rörigt\n**Varmbulle**\n\n\n## Ingredienser\n- **400 g** mjöl"
    out = format_recipe(recipe)
    assert "**" not in out
    assert "\n\n\n" not in out
    assert out.startswith("🍳 Rörigt")


def test_unknown_heading_keeps_text_without_emoji():
    out = format_recipe("# R\n## Tips\nAnvänd jästa deg.")
    assert "\nTips\n" in out


def test_truncates_over_limit_at_line_boundary():
    steps = "\n".join(f"{i}. röra i ingrediens nr {i}" for i in range(1, 400))
    recipe = "## Stor\n## Ingredienser\n- x\n## Steg\n" + steps
    out = format_recipe(recipe, limit=500)
    assert len(out) <= 500
    assert out.endswith("…")
    # every kept line is an intact line of the formatted recipe (no mid-word cuts)
    full = format_recipe(recipe)
    assert full.startswith(out[:-1].rstrip("\n"))


def test_reply_copy_is_fixed():
    assert MESSAGE_LIMIT == 2000  # Instagram hard limit for a text message
    assert HINT_TEXT == (
        "Send me a cooking video as a DM and I'll reply with the full recipe! 🍳 (max 5 videos/day)")
    assert SORRY_TEXT == (
        "Hmm, I couldn't extract a recipe from that video. Make sure it's a cooking video "
        "where the ingredients and steps are shown or said — and try again!")
    assert LIMIT_TEXT == ("You've used your 5 videos for today. Come back tomorrow — "
                          "or send me a video you really needed. 🍳")
    assert BUSY_TEXT == "I'm a bit overwhelmed right now (daily budget spent). Try me again tomorrow!"
