from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Instagram Recipe Bot")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
