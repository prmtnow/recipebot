import uvicorn

from app.config import Settings
from app.main import create_app

# Fail fast at startup on missing configuration.
app = create_app(Settings.from_env())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
