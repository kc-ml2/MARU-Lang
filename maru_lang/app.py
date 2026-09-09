"""FastAPI application composition root."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from maru_lang.api.endpoints.files import router as files_router
from maru_lang.api.endpoints.storages import router as storages_router
from maru_lang.api.endpoints.teams import router as teams_router
from maru_lang.context import AppContext
from maru_lang.core.relation_db import database_context
from maru_lang.adapters.smtp_email import create_email_service
from maru_lang.mcp_server import create_mcp_server
from maru_lang.services.search import create_search_backend
from maru_lang.settings import Settings
from maru_lang.utils.security import TokenCodec

def create_app(settings: Settings | None = None) -> FastAPI:
    """Build MARU with one validated settings object and one DB lifecycle."""
    resolved_settings = settings or Settings.from_env()
    context = AppContext(
        settings=resolved_settings,
        tokens=TokenCodec(resolved_settings.secret_key),
        email=create_email_service(resolved_settings),
        search=create_search_backend(
            resolved_settings.search_backend,
            resolved_settings.ripgrep_path,
        ),
    )
    mcp_server = create_mcp_server(context)
    mcp_app = mcp_server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Schema bootstrap is centralized here until migrations are introduced.
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
            async with mcp_server.session_manager.run():
                yield

    app = FastAPI(
        title="MaruLang API",
        description="A deterministic, team-scoped filesystem access layer for AI agents",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.context = context

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check():
        return {
            "status": "ok",
            "filesystem_search": {
                "backend": context.search.name,
                "version": context.search.version,
                "regex_supported": True,
            },
        }

    app.include_router(teams_router)
    app.include_router(storages_router)
    app.include_router(files_router)
    # Mounted last so REST routes keep precedence while MCP owns /mcp and its
    # protected-resource metadata endpoint.
    app.mount("/", mcp_app)
    return app
