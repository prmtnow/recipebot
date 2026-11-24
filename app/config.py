import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    ig_access_token: str
    ig_account_id: str
    app_secret: str
    verify_token: str
    gemini_api_key: str
    db_path: str = "bot.db"
    max_video_mb: int = 64
    daily_user_limit: int = 5
    daily_spend_cap_usd: float = 20.0
    gemini_model: str = "gemini-3.8-flash"

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        missing = [k for k in
                   ("IG_ACCESS_TOKEN", "IG_ACCOUNT_ID", "APP_SECRET",
                    "VERIFY_TOKEN", "GEMINI_API_KEY")
                   if not env.get(k)]
        if missing:
            raise ValueError(f"missing required env vars: {', '.join(missing)}")
        return cls(
            ig_access_token=env["IG_ACCESS_TOKEN"],
            ig_account_id=env["IG_ACCOUNT_ID"],
            app_secret=env["APP_SECRET"],
            verify_token=env["VERIFY_TOKEN"],
            gemini_api_key=env["GEMINI_API_KEY"],
            db_path=env.get("DB_PATH", "bot.db"),
            max_video_mb=int(env.get("MAX_VIDEO_MB", "64")),
            daily_user_limit=int(env.get("DAILY_USER_LIMIT", "5")),
            daily_spend_cap_usd=float(env.get("DAILY_SPEND_CAP_USD", "20.0")),
            gemini_model=env.get("GEMINI_MODEL", "gemini-3.8-flash"),
        )
