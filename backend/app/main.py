"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import error_body, install_error_handlers
from app.core.masking import MaskingLogFilter
from app.nodes.base import discover

API_PREFIX = "/api"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com")


def _install_log_masking() -> None:
    root = logging.getLogger()
    flt = MaskingLogFilter()
    for h in root.handlers:
        if not any(isinstance(f, MaskingLogFilter) for f in h.filters):
            h.addFilter(flt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            if not any(isinstance(f, MaskingLogFilter) for f in h.filters):
                h.addFilter(flt)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    _install_log_masking()
    discover()
    from app.db import get_db
    from app.engine.services import preload_credentials

    try:
        preload_credentials(get_db())
        from app.seed.builtin_templates import seed_builtin_templates

        seed_builtin_templates(get_db())
    except Exception:  # noqa: BLE001 - schema may not exist yet on first start; masking patterns still apply
        logging.getLogger(__name__).warning("credential preload for masking skipped (database not ready)")
    task = None
    stop = asyncio.Event()
    if get_settings().inprocess_worker:
        from app.db import get_db
        from app.engine.worker import Worker

        worker = Worker(get_db(), f"api-{socket.gethostname()}-{os.getpid()}", get_settings().worker_poll_seconds)
        task = asyncio.create_task(worker.serve(stop))
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            await task


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI Security Workflow API", version="0.2.0", docs_url="/docs", openapi_url="/openapi.json",
                  lifespan=lifespan)
    install_error_handlers(app)

    @app.middleware("http")
    async def limits_and_headers(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_body_bytes:
            return JSONResponse(error_body("payload_too_large", "тело запроса слишком большое"), status_code=413)
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path in ("/docs", "/redoc"):
            response.headers["Content-Security-Policy"] = DOCS_CSP
        return response

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list(), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "Last-Event-ID"], max_age=600)

    from app.api import (
        ai,
        auth,
        autofix,
        ci,
        credentials,
        nodes,
        projects,
        runs,
        scoring,
        templates,
        webhooks,
        workflows,
        workspaces,
    )
    from app.api import settings as settings_api

    for r in (auth.router, workspaces.router, projects.router, nodes.router, workflows.router, runs.router,
              credentials.router, settings_api.router, ai.router, templates.router, ci.router,
              webhooks.router, scoring.router, autofix.router):
        app.include_router(r, prefix=API_PREFIX)

    @app.get("/api/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
