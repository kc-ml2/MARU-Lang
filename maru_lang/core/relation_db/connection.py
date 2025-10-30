from tortoise import Tortoise
from tortoise.contrib.fastapi import RegisterTortoise
from functools import partial
from maru_lang.configs.system_config import get_system_config
from contextlib import asynccontextmanager
from typing import Awaitable, Callable
import asyncio

config = get_system_config()


def run_with_orm_context(coro: Callable[..., Awaitable], *args, **kwargs):
    async def runner():
        async with orm_context():
            return await coro(*args, **kwargs)
    return asyncio.run(runner())


def get_register_orm():
    # partial을 사용해서 미리 설정된 RegisterTortoise를 반환
    return partial(
        RegisterTortoise,
        generate_schemas=True,
        add_exception_handlers=True,
        db_url=config.database.get_database_url(),
        modules={"models": [
            "maru_lang.core.relation_db.models", "aerich.models"]},
        use_tz=True,
    )


@asynccontextmanager
async def orm_context():
    await Tortoise.init(
        db_url=config.database.get_database_url(),
        modules={"models": [
            "maru_lang.core.relation_db.models", "aerich.models"]},
        use_tz=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()