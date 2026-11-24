import os

import uvicorn

from app.config import Settings
from app.main import create_app

# Fail fast at startup on missing configuration.
app = create_app(Settings.from_env())

if __name__ == "__main__":
    # Railway/Fly inject PORT.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
