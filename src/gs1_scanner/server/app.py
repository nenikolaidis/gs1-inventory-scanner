"""The FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gs1_scanner import __version__
from gs1_scanner.server import migrate
from gs1_scanner.server.config import Settings
from gs1_scanner.server.db import make_engine, make_session_factory
from gs1_scanner.server.routes import auth, catalog, scans, users

# The built web app (see web/), copied here by the build.
STATIC_DIR = Path(__file__).parent / "static"

# Browsers can't add custom headers to cross-site form posts, so requiring this
# header on state-changing API calls blocks CSRF (the session cookie is also SameSite=Lax).
CSRF_HEADER = "X-Requested-With"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        migrate.upgrade(engine)
        yield
        engine.dispose()

    app = FastAPI(title="GS1 Scanner", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)

    @app.middleware("http")
    async def require_csrf_header(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            request.method not in SAFE_METHODS
            and request.url.path.startswith("/api/")
            and not request.headers.get(CSRF_HEADER)
        ):
            return JSONResponse({"detail": f"Missing {CSRF_HEADER} header."}, status_code=403)
        return await call_next(request)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    for module in (auth, users, scans, catalog):
        app.include_router(module.router)

    if (STATIC_DIR / "index.html").exists():
        _serve_web_app(app)
    return app


def _serve_web_app(app: FastAPI) -> None:
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    index = STATIC_DIR / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file = (STATIC_DIR / path).resolve()
        if path and file.is_file() and file.is_relative_to(STATIC_DIR.resolve()):
            return FileResponse(file)
        # Client-side routes (/scan, /history, ...) all load the app shell.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
