"""Tortoise ORM 1.x context lifecycle."""
from __future__ import annotations

from contextlib import asynccontextmanager

from tortoise import Tortoise
from tortoise.context import TortoiseContext

MODELS = ["maru_lang.core.relation_db.models"]


async def open_database(
    database_url: str, *, enable_global_fallback: bool = False
) -> TortoiseContext:
    """Open a DB context; ASGI servers opt into cross-task access."""
    return await Tortoise.init(
        db_url=database_url,
        modules={"models": MODELS},
        use_tz=True,
        _enable_global_fallback=enable_global_fallback,
    )


@asynccontextmanager
async def database_context(
    database_url: str,
    *,
    generate_schemas: bool = False,
    enable_global_fallback: bool = False,
):
    """Enter and close a Tortoise 1.x context explicitly."""
    context = await open_database(
        database_url, enable_global_fallback=enable_global_fallback
    )
    async with context:
        if generate_schemas:
            await context.generate_schemas()
        if database_url.startswith(("postgres://", "postgresql://", "asyncpg://")):
            connection = context.db("default")
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
                ALTER TABLE source_storage DROP CONSTRAINT IF EXISTS source_storage_type_check;
                ALTER TABLE source_storage ADD CONSTRAINT source_storage_type_check CHECK (
                    (storage_type = 'managed' AND external_path IS NULL)
                    OR (storage_type = 'external' AND external_path IS NOT NULL
                        AND owner_type = 'system' AND owner_team_id IS NULL AND auto_attach = FALSE)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uidx_team_personal_manager
                    ON team (manager_id)
                    WHERE is_personal = TRUE;
                """
            )
        yield context
