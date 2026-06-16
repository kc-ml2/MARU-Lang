"""Config-driven LangGraph checkpointer (saver) factory.

Selects the persistent saver based on MARU's configured database:
    - sqlite   -> AsyncSqliteSaver (separate file from the relational DB)
    - postgres -> AsyncPostgresSaver (same DB, separate checkpoint tables)

The saver is an async context manager and owns a DB connection, so it must be
created once for the app lifetime (see app lifespan) rather than per request.
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from maru_lang.configs import get_config


@asynccontextmanager
async def build_checkpointer() -> AsyncIterator[object]:
    """Yield an initialized LangGraph checkpointer based on config.

    The checkpointer's tables are created via ``.setup()`` on entry (idempotent).
    """
    scheme, target = get_config().resolve_checkpoint_target()

    if scheme == "sqlite":
        async with AsyncSqliteSaver.from_conn_string(target) as saver:
            await saver.setup()
            yield saver
        return

    if scheme == "postgres":
        # NOTE: imported here, not at module top, on purpose. AsyncPostgresSaver
        # pulls in psycopg -> libpq at import time, which raises on machines
        # without libpq (dev/CI/sqlite-only). A top-level import would break the
        # whole module for sqlite users, so this one stays scheme-local.
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(target) as saver:
            await saver.setup()
            yield saver
        return

    raise ValueError(f"Unsupported checkpoint scheme: {scheme!r}")
