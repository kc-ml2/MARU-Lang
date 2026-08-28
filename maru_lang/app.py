"""FastAPI application composition root."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from maru_lang.api.endpoints.auth import router as auth_router
from maru_lang.api.endpoints.storages import router as storages_router
from maru_lang.api.endpoints.teams import router as teams_router
from maru_lang.context import AppContext
from maru_lang.core.relation_db import database_context
from maru_lang.adapters.smtp_email import create_email_service
from maru_lang.settings import Settings
from maru_lang.utils.security import TokenCodec

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build MARU with one validated settings object and one DB lifecycle."""
    resolved_settings = settings or Settings.from_env()
    context = AppContext(
        settings=resolved_settings,
        tokens=TokenCodec(resolved_settings.secret_key, resolved_settings.salt),
        email=create_email_service(resolved_settings),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Schema creation remains temporary until migrations are introduced.
        async with database_context(
            resolved_settings.database_url,
            generate_schemas=True,
        ):
            from maru_lang.services.system_storage import (
                ensure_system_storages,
                reconcile_system_storage_links,
            )
            from maru_lang.services.team import reconcile_team_storage

            resolved_settings.filesystem_root.mkdir(parents=True, exist_ok=True)
            await ensure_system_storages(resolved_settings.filesystem_root)
            await reconcile_team_storage(resolved_settings.filesystem_root)
            await reconcile_system_storage_links()
            yield

    app = FastAPI(
        title="MaruLang API",
        description="Filesystem retrieval server with HTTP API and MCP transports",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.context = context
    @app.middleware("http")
    async def add_access_token_header(request: Request, call_next):
        response = await call_next(request)
        if hasattr(request.state, "new_access_token"):
            response.headers["X-Access-Token"] = request.state.new_access_token
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Access-Token"],
    )

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(teams_router)
    app.include_router(storages_router)
    return app
