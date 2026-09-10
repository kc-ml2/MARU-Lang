"""Contract tests for the required ripgrep filesystem search engine."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maru_lang.services.search import RipgrepSearch


@unittest.skipUnless(shutil.which("rg"), "ripgrep is required for search tests")
class RipgrepSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root / "docs").mkdir()
        (self.root / ".hidden").mkdir()
        (self.root / "docs" / "alpha.md").write_text(
            "first line\n한글 needle here\nNEEDLE again\n", encoding="utf-8"
        )
        (self.root / "docs" / "beta.txt").write_text(
            "needle elsewhere\n", encoding="utf-8"
        )
        (self.root / ".hidden" / "note.md").write_text(
            "hidden needle\n", encoding="utf-8"
        )
        (self.root / ".ignore").write_text("docs/beta.txt\n", encoding="utf-8")
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("needle outside\n", encoding="utf-8")
        self.outside = outside
        (self.root / "outside-link").symlink_to(outside)
        self.search = RipgrepSearch(shutil.which("rg"))

    def tearDown(self):
        self.directory.cleanup()
        self.outside.unlink(missing_ok=True)

    def test_find_files_is_sorted_hidden_and_does_not_follow_symlinks(self):
        result = self.search.find_files(self.root, include_globs=("*.md",))
        self.assertEqual(
            [item["path"] for item in result.results],
            [".hidden/note.md", "docs/alpha.md"],
        )
        self.assertEqual(result.backend, "ripgrep")
        self.assertFalse(result.truncated)

    def test_literal_search_returns_utf8_byte_column_and_ignores_ignore_files(self):
        result = self.search.search_text(
            self.root, "needle", include_globs=("docs/**",)
        )
        self.assertEqual(
            [(item["path"], item["line"], item["byte_column"]) for item in result.results],
            [("docs/alpha.md", 2, 8), ("docs/beta.txt", 1, 1)],
        )

    def test_regex_case_insensitive_search_and_truncation(self):
        result = self.search.search_text(
            self.root, "needle", mode="regex", case_sensitive=False, max_results=2
        )
        self.assertEqual(len(result.results), 2)
        self.assertTrue(result.truncated)

    def test_subdirectory_results_remain_storage_relative(self):
        result = self.search.find_files(self.root, path="docs", name_glob="*.txt")
        self.assertEqual(result.results, ({"path": "docs/beta.txt", "type": "file"},))

    def test_newline_filename_is_one_path(self):
        (self.root / 'line\nbreak.txt').write_text('needle')
        result = self.search.find_files(self.root, name_glob='line*')
        self.assertEqual(result.results, ({'path': 'line\nbreak.txt', 'type': 'file'},))

    def test_non_utf8_content_does_not_fail_search(self):
        (self.root / 'invalid.txt').write_bytes(b'needle \xff\n')
        result = self.search.search_text(self.root, 'needle', include_globs=('invalid.txt',))
        self.assertEqual(result.results[0]['text'], 'needle \ufffd')

    def test_non_utf8_filename_is_skipped_without_lossy_path(self):
        path = os.fsencode(self.root) + b'/invalid-\xff.txt'
        try:
            file = open(path, 'wb')
        except OSError as exc:
            self.skipTest(f'Filesystem does not support non-UTF-8 filenames: {exc}')
        with file:
            file.write(b'needle')
        files = self.search.find_files(self.root)
        matches = self.search.search_text(self.root, 'needle')
        self.assertFalse(any('invalid-' in item['path'] for item in files.results))
        self.assertFalse(any('invalid-' in item['path'] for item in matches.results))

    def test_output_budget_marks_partial_results(self):
        (self.root / 'large.txt').write_text('needle ' * 10000)
        search = RipgrepSearch(max_output_bytes=1024)
        result = search.search_text(self.root, 'needle', include_globs=('large.txt',))
        self.assertTrue(result.truncated)

    def test_exact_result_limit_is_not_truncated(self):
        result = self.search.find_files(self.root, name_glob='alpha.md', max_results=1)
        self.assertFalse(result.truncated)

    def test_missing_executable_fails_fast(self):
        with patch("maru_lang.services.search.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ripgrep is required"):
                RipgrepSearch()


if __name__ == "__main__":
    unittest.main()
