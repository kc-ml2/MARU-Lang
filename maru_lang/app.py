import asyncio
import logging
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager, AsyncExitStack
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from maru_lang.core.relation_db import get_register_orm
from maru_lang.configs import get_config
from maru_lang.graph.ingest.embedder import get_embeddings
from maru_lang.graph.checkpoint import build_checkpointer
from maru_lang.graph.registry import GRAPH_REGISTRY
from maru_lang.core.llm import get_llm_manager
from maru_lang.services.llm import sync_llms_from_config
from maru_lang.api.endpoints.auth import router as auth_router
from maru_lang.api.endpoints.chat import router as chat_router
from maru_lang.api.endpoints.config import router as config_router
from maru_lang.api.endpoints.ingest import router as ingest_router
from maru_lang.api.endpoints.internal import router as internal_router
from maru_lang.api.endpoints.teams import router as teams_router
from maru_lang.api.endpoints.session import router as session_router
from maru_lang.api.endpoints.memory import router as memory_router
from maru_lang.api.endpoints.llm import router as llm_router


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

            # 3. Pre-load embedding model (device from config; None=auto/GPU).
            #    Pass embedding_device so the cache key matches the ingest path.
            print(f"Loading embedding model: {cfg.embedding_model}...")
            await asyncio.to_thread(get_embeddings, cfg.embedding_model, cfg.embedding_device)
            print(f"✓ Embedding model loaded: {cfg.embedding_model} (device={cfg.embedding_device or 'auto'})")

            # 4. Initialize the LangGraph checkpointer (app-scoped, persistent).
            #    Kept alive for the whole app lifetime via an AsyncExitStack on
            #    app.state; closed in _default_shutdown.
            self.state.exit_stack = AsyncExitStack()
            self.state.checkpointer = await self.state.exit_stack.enter_async_context(
                build_checkpointer()
            )
            scheme, _ = cfg.resolve_checkpoint_target()
            print(f"✓ Checkpointer initialized ({scheme})")

            # 4.5 Mirror config LLMs into the DB (source of truth = config).
            #     Enables FK integrity for User.assigned_llm / Conversation.llm_used.
            await sync_llms_from_config()

            # 5. Compile every registered graph once (app-scoped, shared across
            #    connections; state lives in the checkpointer keyed by thread_id).
            #    Two maps are built:
            #      - graphs: a default/fallback map (gid -> graph) using the config
            #        fallback chain, for users with no/disabled assignment.
            #      - graphs_by_llm: one graph per enabled LLM (llm_name -> {gid -> graph}),
            #        so each user runs every node on their assigned LLM.
            #    The graph_router picks the gid per request. Empty if no LLM.
            self.state.graphs = {}
            self.state.graphs_by_llm = {}
            self.state.models_by_llm = {}    # llm_name -> BaseChatModel (for L1 routing)
            self.state.default_llm_name = None
            self.state.router_model = None
            try:
                clients = get_llm_manager().clients  # enabled LLM clients (name + model)
                if not clients:
                    raise RuntimeError("No LLM model available. Check llms config.")

                # Every graph/model is a single LLM with NO fallback chain: a turn
                # (L1 routing + all graph nodes) runs on exactly one LLM, so
                # Conversation.llm_used is an accurate record of what actually ran.
                for client in clients:
                    self.state.graphs_by_llm[client.config.name] = {
                        gid: spec.factory(model=client.model, checkpointer=self.state.checkpointer)
                        for gid, spec in GRAPH_REGISTRY.items()
                    }
                    self.state.models_by_llm[client.config.name] = client.model

                # Default (used for unassigned/disabled): the first enabled LLM.
                # Reuse its already-compiled per-LLM graphs/model (no re-compile).
                default_client = clients[0]
                self.state.default_llm_name = default_client.config.name
                self.state.graphs = self.state.graphs_by_llm[default_client.config.name]
                self.state.router_model = default_client.model

                print(f"✓ Graphs compiled: {', '.join(self.state.graphs) or '(none)'} "
                      f"× {len(self.state.graphs_by_llm)} LLM(s)")
            except RuntimeError as e:
                logger.warning(f"Graphs not compiled — chat disabled: {e}")

            # 6. Ingest task queue (optional). When task_queue_enabled, create an
            #    ARQ Redis pool used by /ingest/upload to enqueue embedding jobs.
            #    Its presence on app.state is the on/off switch for queue mode.
            self.state.arq = None
            if cfg.queue_enabled:
                from arq import create_pool
                from arq.connections import RedisSettings
                self.state.arq = await create_pool(RedisSettings.from_dsn(cfg.redis_url))
                print(f"✓ Ingest task queue enabled (ARQ @ {cfg.redis_url})")

            # 7. Observability (optional). Initialize Langfuse eagerly so key/
            #    install problems surface at startup, not on the first chat turn.
            from maru_lang.core.observability import get_langfuse_handler
            if get_langfuse_handler() is not None:
                print(f"✓ Langfuse tracing enabled (@ {cfg.langfuse.host})")

            print("=" * 60)
            print("✨ Application startup complete!")
            print("=" * 60)

    async def _default_shutdown(self):
        """Default shutdown routine."""
        # Clean up resources such as database connections
        print("🔄 Shutting down application...")

        # Close the ingest task queue pool, if it was created.
        arq = getattr(self.state, "arq", None)
        if arq is not None:
            await arq.close()
            print("✓ Ingest task queue pool closed")

        # Close the LangGraph checkpointer (and its DB connection).
        exit_stack = getattr(self.state, "exit_stack", None)
        if exit_stack is not None:
            await exit_stack.aclose()
            print("✓ Checkpointer closed")

        # Close Tortoise ORM connections
        from tortoise import Tortoise
        await Tortoise.close_connections()
        print("✓ Database connections closed")

        # Flush any buffered Langfuse traces (no-op when disabled).
        from maru_lang.core.observability import flush_langfuse
        flush_langfuse()

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
            self.include_router(config_router)
            self.include_router(ingest_router)
            self.include_router(internal_router)
            self.include_router(teams_router)
            self.include_router(session_router)
            self.include_router(memory_router)
            self.include_router(llm_router)

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
