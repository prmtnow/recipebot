from app.replies import BUSY_TEXT, HINT_TEXT, LIMIT_TEXT, SORRY_TEXT, chunk_recipe

SHORT = "## Brød\n## Ingredienser\n400 g mel\n## Steg\n1. Bland. 2. Bag."


def _make_long_recipe(total_chars: int) -> str:
    parts = ["## Tærter", "## Ingredienser", "400 g mel"]
    i = 0
    while len("\n".join(parts)) < total_chars:
        i += 1
        parts.append(f"{i}. bland mel og vand ingrediens nr {i}")
    recipe = "\n".join(parts)
    return recipe[: recipe.rfind("\n", 0, total_chars)]


def test_short_recipe_returns_single_chunk():
    assert chunk_recipe(SHORT, 1800) == [SHORT]


def test_long_recipe_splits_on_step_boundary_without_loss():
    recipe = _make_long_recipe(3400)
    chunks = chunk_recipe(recipe, 1800)
    assert len(chunks) == 2
    assert all(len(c) <= 1800 for c in chunks)
    assert all(c.startswith("\n") is False for c in chunks[1:])
    lines = [ln for ln in recipe.split("\n") if ln]
    joined = [ln for c in chunks for ln in c.split("\n") if ln]
    assert joined == lines  # nothing dropped, nothing reordered


def test_hard_split_when_no_newline_split_fits():
    recipe = "x" * 5000
    chunks = chunk_recipe(recipe, 1800)
    assert len(chunks) == 2
    assert "".join(chunks) == recipe


def test_reply_copy_is_fixed():
    assert HINT_TEXT == (
        "Send me a cooking video as a DM and I'll reply with the full recipe! 🍳 (max 5 videos/day)")
    assert SORRY_TEXT == (
        "Hmm, I couldn't extract a recipe from that video. Make sure it's a cooking video "
        "where the ingredients and steps are shown or said — and try again!")
    assert LIMIT_TEXT == ("You've used your 5 videos for today. Come back tomorrow — "
                          "or send me a video you really needed. 🍳")
    assert BUSY_TEXT == "I'm a bit overwhelmed right now (daily budget spent). Try me again tomorrow!"
