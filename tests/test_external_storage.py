import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from maru_lang.services.system_admin import validate_external_path, unregister_external
from maru_lang.utils.file_storage import get_storage_dir


class ExternalStorageTests(unittest.IsolatedAsyncioTestCase):
    def test_path_validation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            managed = root / 'managed'
            external = root / 'external'
            external.mkdir()
            self.assertEqual(validate_external_path(external, managed), external)
            with self.assertRaises(ValueError):
                validate_external_path(root, managed)
            alias = root / 'alias'
            alias.symlink_to(external)
            with self.assertRaises(ValueError):
                validate_external_path(alias, managed)
            storage = SimpleNamespace(storage_type='external', owner_type='system',
                                      external_path=str(external))
            self.assertEqual(get_storage_dir(managed, storage), external)

    async def test_unregister_keeps_files(self):
        with TemporaryDirectory() as directory:
            file = Path(directory) / 'keep.txt'
            file.write_text('original')
            storage = SimpleNamespace(delete=AsyncMock())
            with patch('maru_lang.services.system_admin.external_storage',
                       new=AsyncMock(return_value=storage)), \
                 patch('maru_lang.services.system_admin.TeamStorageLink.exists',
                       new=AsyncMock(return_value=False)):
                await unregister_external('id')
                storage.delete.assert_awaited_once()
                self.assertEqual(file.read_text(), 'original')

    async def test_shared_storage_cannot_be_unregistered(self):
        storage = SimpleNamespace(delete=AsyncMock())
        with patch('maru_lang.services.system_admin.external_storage',
                   new=AsyncMock(return_value=storage)), \
             patch('maru_lang.services.system_admin.TeamStorageLink.exists',
                   new=AsyncMock(return_value=True)):
            with self.assertRaises(ValueError):
                await unregister_external('id')
            storage.delete.assert_not_awaited()
