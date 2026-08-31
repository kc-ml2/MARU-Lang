"""Tortoise ORM 1.x context lifecycle."""
from __future__ import annotations

from contextlib import asynccontextmanager

from tortoise import Tortoise
from tortoise.context import TortoiseContext

MODELS = ["maru_lang.core.relation_db.models"]


async def open_database(database_url: str) -> TortoiseContext:
    """Open an isolated Tortoise 1.x context for the current async context."""
    return await Tortoise.init(
        db_url=database_url,
        modules={"models": MODELS},
        use_tz=True,
        _enable_global_fallback=False,
    )


@asynccontextmanager
async def database_context(
    database_url: str,
    *,
    generate_schemas: bool = False,
):
    """Enter and close a Tortoise 1.x context explicitly."""
    context = await open_database(database_url)
    async with context:
        if generate_schemas:
            await context.generate_schemas()
        if database_url.startswith(("postgres://", "postgresql://", "asyncpg://")):
            connection = context.get_connection("default")
            await connection.execute_script(
                """
                ALTER TABLE source_storage
                    DROP CONSTRAINT IF EXISTS source_storage_owner_check;
                ALTER TABLE source_storage
                    ALTER COLUMN owner_type SET NOT NULL;
                ALTER TABLE source_storage
                    ADD CONSTRAINT source_storage_owner_check CHECK (
                        (
                            owner_type = 'system'
                            AND owner_team_id IS NULL
                            AND system_key IS NOT NULL
                        )
                        OR
                        (
                            owner_type = 'team'
                            AND owner_team_id IS NOT NULL
                            AND system_key IS NULL
                        )
                    );
                CREATE UNIQUE INDEX IF NOT EXISTS uidx_team_personal_manager
                    ON team (manager_id)
                    WHERE is_personal = TRUE;
                """
            )
        yield context
