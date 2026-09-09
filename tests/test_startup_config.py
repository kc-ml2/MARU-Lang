import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from maru_lang.cli import main
from maru_lang.core.relation_db.connection import database_context
from maru_lang.settings import Settings


class StartupConfigTests(unittest.TestCase):
    def test_default_config_and_explicit_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path.cwd()
            try:
                os.chdir(directory)
                text = ('database:\n  url: postgresql://localhost/maru\n'
                        'auth:\n  secret_key: ' + 'x' * 32 + '\n'
                        'filesystem:\n  root: /tmp/maru\n'
                        'server:\n  public_url: https://default.example\n')
                Path('config.yaml').write_text(text)
                Path('other.yaml').write_text(text.replace('default.example', 'other.example'))
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(Settings.from_env().public_url, 'https://default.example')
                    with patch.dict(os.environ, {'MARU_CONFIG': 'other.yaml'}):
                        self.assertEqual(Settings.from_env().public_url, 'https://other.example')
                        self.assertEqual(Settings.from_env('config.yaml').public_url,
                                         'https://default.example')
                    with patch.dict(os.environ, {'MARU_CONFIG': 'missing.yaml'}):
                        with self.assertRaises(FileNotFoundError):
                            Settings.from_env()
                    Path('config.yaml').unlink()
                    with patch.dict(os.environ, {
                        'MARU_DATABASE_URL': 'postgresql://localhost/maru',
                        'MARU_SECRET_KEY': 'x' * 32, 'MARU_FILESYSTEM_ROOT': '/tmp/maru',
                    }):
                        self.assertEqual(Settings.from_env().filesystem_root, Path('/tmp/maru'))
            finally:
                os.chdir(original)

    def test_serve_passes_configuration_and_bind_options(self):
        with patch('sys.argv', ['maru', '--config', 'chosen.yaml', 'serve', '--port', '8123']), \
             patch('maru_lang.cli.Settings.from_env') as settings, \
             patch('maru_lang.app.create_app') as create, \
             patch('uvicorn.run') as run:
            main()
            settings.assert_called_once_with(Path('chosen.yaml'))
            create.assert_called_once_with(settings.return_value)
            run.assert_called_once_with(create.return_value, host='127.0.0.1', port=8123)


class DatabaseContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_bootstrap_uses_context_db(self):
        # Spec enforces the installed TortoiseContext API, including absence of
        # get_connection. Exercise the PostgreSQL-only branch without a server.
        from tortoise.context import TortoiseContext

        context = MagicMock(spec=TortoiseContext)
        context.__aenter__ = AsyncMock(return_value=context)
        context.__aexit__ = AsyncMock(return_value=False)
        context.generate_schemas = AsyncMock()
        connection = MagicMock()
        connection.execute_script = AsyncMock()
        context.db.return_value = connection
        with patch('maru_lang.core.relation_db.connection.open_database',
                   new=AsyncMock(return_value=context)):
            async with database_context('postgresql://localhost/maru', generate_schemas=True):
                pass
        context.db.assert_called_once_with('default')
        context.generate_schemas.assert_awaited_once()
        connection.execute_script.assert_awaited_once()
