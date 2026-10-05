"""The FastAPI application."""

from __future__ import annotations

import mimetypes
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
from gs1_scanner.server.deps import CurrentUser
from gs1_scanner.server.routes import audit as audit_routes
from gs1_scanner.server.routes import auth, catalog, counts, scans, users
from gs1_scanner.server.routes import stock as stock_routes

# Older Pythons don't know these, and browsers need them to be right.
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/manifest+json", ".webmanifest")

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

    @app.get("/api/config", tags=["meta"])
    def client_config(_user: CurrentUser) -> dict[str, object]:
        """Settings the web app needs to know about."""
        return {
            "version": __version__,
            "expiry_warning_days": settings.expiry_warning_days,
            "label_printer": bool(settings.zebra_printer),
            "label_dpi": settings.label_dpi,
            "label_size": settings.label_size,
        }

    for module in (auth, users, scans, catalog, stock_routes, counts, audit_routes):
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
            # The service worker must always be fresh, or app updates never arrive.
            headers = {"Cache-Control": "no-cache"} if path == "sw.js" else None
            return FileResponse(file, headers=headers)
        # Client-side routes (/scan, /history, ...) all load the app shell.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
