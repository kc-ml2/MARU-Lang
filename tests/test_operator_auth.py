import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from maru_lang.cli import deliver_token, parser
from maru_lang.core.relation_db.connection import database_context
from maru_lang.core.relation_db.models.auth import ApiToken, Team, User
from maru_lang.dependencies.auth import get_user
from maru_lang.mcp_server import MaruTokenVerifier
from maru_lang.services.api_tokens import authenticate_token, issue_token, parse_expiry, revoke_token
from maru_lang.services.operator_users import add_user
from maru_lang.settings import Settings


class ConfigTests(unittest.TestCase):
    def test_yaml_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text('database:\n  url: postgresql://localhost/maru\nauth:\n'
                            '  secret_key: ' + 'x' * 32 + '\n  allowed_domains: [kc-ml2.com]\n'
                            'filesystem:\n  root: /srv/maru/files\n')
            with patch.dict(os.environ, {}, clear=True):
                settings = Settings.from_env(path)
                self.assertEqual(settings.allowed_domains, ('kc-ml2.com',))
                with patch.dict(os.environ, {'MARU_SEARCH_BACKEND': 'python'}):
                    self.assertEqual(Settings.from_env(path).search_backend, 'python')
                path.write_text('filesystem:\n  typo: true\n')
                with self.assertRaisesRegex(RuntimeError, 'Unknown configuration key'):
                    Settings.from_env(path)

    def test_cli_and_duration(self):
        args = parser().parse_args(['--config', '/tmp/maru.yaml', 'add',
                                   'ji@kc-ml2.com', '-t', 'ml2', '-r', 'admin'])
        self.assertEqual(args.role, 'admin')
        self.assertIsNone(args.expires_in)
        self.assertEqual(parse_expiry('90d'), timedelta(days=90))
        for value in ['0d', '-1d', 'forever', '2']:
            with self.assertRaises(ValueError):
                parse_expiry(value)


class OperatorAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = database_context('sqlite://:memory:', generate_schemas=True)
        await self.db.__aenter__()
        self.settings = Settings(database_url='postgresql://localhost/maru',
                                 secret_key='x' * 32,
                                 filesystem_root=Path(self.directory.name))

    async def asyncTearDown(self):
        await self.db.__aexit__(None, None, None)
        self.directory.cleanup()

    async def test_provision_and_idempotence(self):
        user, result = await add_user(self.settings, 'ji@kc-ml2.com', 'ml2', 'admin')
        self.assertTrue(result['team_created'])
        self.assertEqual((await Team.get(id=result['team_id'])).manager_id, user.id)
        _, again = await add_user(self.settings, user.email, 'ml2', 'admin')
        self.assertFalse(again['member_created'])
        with self.assertRaises(ValueError):
            await add_user(self.settings, user.email, 'ml2', 'member')
        with self.assertRaises(ValueError):
            await add_user(self.settings, 'other@kc-ml2.com', 'new', 'member')
        self.assertFalse(await User.exists(email='other@kc-ml2.com'))

    async def test_api_token_shared_by_mcp_and_http(self):
        user = await User.create(email='ji@kc-ml2.com')
        record, token = await issue_token(user)
        self.assertIsNone(record.expires_at)
        self.assertNotEqual(record.token_hash, token)
        self.assertEqual(len(record.token_hash), 64)
        verifier = MaruTokenVerifier(SimpleNamespace())
        access = await verifier.verify_token(token)
        self.assertEqual(access.subject, str(user.id))
        self.assertIsNone(access.expires_at)
        credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
        self.assertEqual((await get_user(credentials)).id, user.id)
        await revoke_token(record.id)
        self.assertIsNone(await verifier.verify_token(token))
        with self.assertRaises(HTTPException):
            await get_user(credentials)
        self.assertIsNone(await authenticate_token('old.jwt.token'))
        expired, expired_token = await issue_token(user, timedelta(seconds=-1))
        self.assertIsNone(await authenticate_token(expired_token))
        await User.filter(id=user.id).delete()
        self.assertFalse(await ApiToken.exists(id=expired.id))

    async def test_email_failure_keeps_token_and_prints_before_delivery(self):
        user = await User.create(email='ji@kc-ml2.com')
        output = io.StringIO()

        async def fail(*args):
            self.assertIn('maru_', output.getvalue())
            raise RuntimeError('SMTP down')

        with redirect_stdout(output), patch('maru_lang.cli.create_email_service',
                return_value=SimpleNamespace(send_api_token=AsyncMock(side_effect=fail))):
            result = await deliver_token(self.settings, user, None)
        self.assertEqual(result['email_status'], 'failed')
        token = json.loads(output.getvalue())['token']
        self.assertIsNotNone(await authenticate_token(token))
        self.assertNotIn(token, json.dumps(result))
