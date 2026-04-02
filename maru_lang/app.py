import asyncio
import logging
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from maru_lang.core.relation_db import get_register_orm
from maru_lang.configs import get_config
from maru_lang.api.endpoints.auth import router as auth_router
from maru_lang.api.endpoints.chat import router as chat_router
from maru_lang.api.endpoints.ingest import router as ingest_router
from maru_lang.api.endpoints.sync import router as sync_router
from maru_lang.api.endpoints.teams import router as teams_router


class MaruLangApp(FastAPI):
    """Extensible MaruLang application class.

    Other projects can inherit from this class to add custom functionality.
    """

    def __init__(
        self,
        title: str = "MaruLang API",
        description: str = "Advanced AI Agent Framework with RAG capabilities",
        version: str = "1.0.0",
        cors_origins: Optional[List[str]] = None,
        include_default_routers: bool = True,
        **fastapi_kwargs
    ):
        # Initialize custom hooks (before calling FastAPI.__init__)
        self._startup_hooks: List[Callable] = []
        self._shutdown_hooks: List[Callable] = []
        self._middleware_hooks: List[Callable] = []
        self._router_hooks: List[Callable] = []

        self.cors_origins = cors_origins or self._get_default_cors_origins()
        self.include_default_routers = include_default_routers

        # Create lifespan context manager
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # When the app starts
            await self._startup_sequence()
            yield
            # When the app shuts down
            await self._shutdown_sequence()

        # Initialize the FastAPI application
        super().__init__(
            title=title,
            description=description,
            version=version,
            lifespan=lifespan,
            **fastapi_kwargs
        )

        # Configure FastAPI extensions and middleware
        add_pagination(self)
        self._setup_middleware()
        self._setup_routers()

    def _get_default_cors_origins(self) -> List[str]:
        """Return default CORS origins."""
        return [
            "http://localhost:5173",  # Vite dev server
            # Add more default origins as needed
        ]

    async def _startup_sequence(self):
        """App startup sequence."""
        # Default startup logic
        await self._default_startup()

        # Run custom startup hooks
        for hook in self._startup_hooks:
            if asyncio.iscoroutinefunction(hook):
                await hook(self)
            else:
                hook(self)

    async def _shutdown_sequence(self):
        """App shutdown sequence."""
        # Default shutdown logic
        await self._default_shutdown()

        # Run custom shutdown hooks
        for hook in self._shutdown_hooks:
            if asyncio.iscoroutinefunction(hook):
                await hook(self.app)
            else:
                hook(self.app)

    async def _default_startup(self):
        """Default startup routine."""
        # TODO Initialize logging system
        cfg = get_config()

        if not cfg.llms:
            logger.warning("No LLM configurations found - chat will not work until configured")

        # 2. Register ORM
        print("Initializing databases...")
        register_orm = get_register_orm()
        async with register_orm(self):

            print("=" * 60)
            print("✨ Application startup complete!")
            print("=" * 60)

    async def _default_shutdown(self):
        """Default shutdown routine."""
        # Clean up resources such as database connections
        print("🔄 Shutting down application...")

        # Close Tortoise ORM connections
        from tortoise import Tortoise
        await Tortoise.close_connections()
        print("✓ Database connections closed")

        print("✨ Shutdown complete")

    def _setup_middleware(self):
        """Configure middleware."""
        # Add logging middleware

        # Basic access-token middleware
        @self.middleware("http")
        async def add_access_token_header(request: Request, call_next):
            response = await call_next(request)
            if hasattr(request.state, "new_access_token"):
                response.headers["X-Access-Token"] = request.state.new_access_token
            return response

        # CORS middleware
        self.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Access-Token"],
        )

        # Run custom middleware hooks
        for hook in self._middleware_hooks:
            hook(self.app)

    def _setup_routers(self):
        """Configure routers."""
        # Default health-check endpoint
        @self.get("/health")
        async def health_check():
            return {"status": "ok"}

        # Include default routers
        if self.include_default_routers:
            self.include_router(chat_router)
            self.include_router(auth_router)
            self.include_router(ingest_router)
            self.include_router(sync_router)
            self.include_router(teams_router)

        # Run custom router hooks
        for hook in self._router_hooks:
            hook(self.app)

    # Extension helpers
    def add_startup_hook(self, func: Callable):
        """Add a function to run at app startup."""
        self._startup_hooks.append(func)
        return self

    def add_shutdown_hook(self, func: Callable):
        """Add a function to run at app shutdown."""
        self._shutdown_hooks.append(func)
        return self

    def add_middleware_hook(self, func: Callable):
        """Add a middleware hook."""
        self._middleware_hooks.append(func)
        return self

    def add_router_hook(self, func: Callable):
        """Add a router hook."""
        self._router_hooks.append(func)
        return self

    def get_fastapi_app(self) -> FastAPI:
        """Return the underlying FastAPI app instance."""
        return self

    def on_event(self, event_type: str):
        """Event decorator (deprecated in newer FastAPI, kept for compatibility)."""
        if hasattr(super(), 'on_event'):
            return super().on_event(event_type)
        else:
            # For newer FastAPI versions, use startup/shutdown hooks
            if event_type == "startup":
                def decorator(func):
                    self.add_startup_hook(func)
                    return func
                return decorator
            elif event_type == "shutdown":
                def decorator(func):
                    self.add_shutdown_hook(func)
                    return func
                return decorator
            else:
                raise ValueError(f"Unsupported event type: {event_type}")

    def startup(self):
        """Startup event decorator."""
        def decorator(func):
            self.add_startup_hook(func)
            return func
        return decorator

    def shutdown(self):
        """Shutdown event decorator."""
        def decorator(func):
            self.add_shutdown_hook(func)
            return func
        return decorator


# Convenience factory for the default app instance
def create_app(**kwargs) -> MaruLangApp:
    """Create the default MaruLang app."""
    return MaruLangApp(**kwargs)


default_app = create_app()
