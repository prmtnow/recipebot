import pytest

from app.config import Settings

REQUIRED = {
    "IG_ACCESS_TOKEN": "t",
    "IG_ACCOUNT_ID": "123",
    "APP_SECRET": "s",
    "VERIFY_TOKEN": "v",
    "GEMINI_API_KEY": "g",
}


def test_missing_required_var_raises():
    env = dict(REQUIRED)
    del env["IG_ACCESS_TOKEN"]
    with pytest.raises(ValueError, match="IG_ACCESS_TOKEN"):
        Settings.from_env(env)


def test_empty_required_var_raises():
    env = dict(REQUIRED, APP_SECRET="")
    with pytest.raises(ValueError, match="APP_SECRET"):
        Settings.from_env(env)


def test_defaults_applied():
    s = Settings.from_env(REQUIRED)
    assert s.ig_access_token == "t"
    assert s.ig_account_id == "123"
    assert s.db_path == "bot.db"
    assert s.max_video_mb == 64
    assert s.daily_user_limit == 5
    assert s.daily_spend_cap_usd == 20.0
    assert s.gemini_model == "gemini-3.6-flash"


def test_overrides_applied():
    s = Settings.from_env(REQUIRED | {"DB_PATH": "x.db", "MAX_VIDEO_MB": "10",
                                      "DAILY_USER_LIMIT": "3", "DAILY_SPEND_CAP_USD": "1.5",
                                      "GEMINI_MODEL": "gemini-3.5-flash"})
    assert s.db_path == "x.db"
    assert s.max_video_mb == 10
    assert s.daily_user_limit == 3
    assert s.daily_spend_cap_usd == 1.5
    assert s.gemini_model == "gemini-3.5-flash"
