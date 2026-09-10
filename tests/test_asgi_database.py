"""Request tasks must work without inheriting lifespan ContextVars."""
import asyncio
import contextvars
import unittest
from types import SimpleNamespace

from fastapi.security import HTTPAuthorizationCredentials
from tortoise.context import get_current_context

from maru_lang.core.relation_db.connection import database_context
from maru_lang.core.relation_db.models.auth import User
from maru_lang.dependencies.auth import get_user
from maru_lang.mcp_server import MaruTokenVerifier
from maru_lang.services.api_tokens import issue_token, revoke_token


class CrossTaskDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_and_mcp_auth_in_independent_request_tasks(self):
        async with database_context('sqlite://:memory:', generate_schemas=True,
                                    enable_global_fallback=True):
            user = await User.create(email='request@example.com')
            record, token = await issue_token(user)

            async def request():
                verifier = MaruTokenVerifier(SimpleNamespace())
                self.assertEqual((await verifier.verify_token(token)).subject, str(user.id))
                credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
                self.assertEqual((await get_user(credentials)).id, user.id)
                await revoke_token(record.id)
                self.assertIsNone(await verifier.verify_token(token))

            await asyncio.create_task(request(), context=contextvars.Context())
        self.assertIsNone(contextvars.Context().run(get_current_context))

    async def test_default_remains_isolated(self):
        async with database_context('sqlite://:memory:', generate_schemas=True):
            async def request():
                with self.assertRaisesRegex(RuntimeError, 'No TortoiseContext'):
                    await User.all()
            await asyncio.create_task(request(), context=contextvars.Context())
