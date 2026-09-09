"""Contract tests for the required ripgrep filesystem search engine."""
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

    def test_missing_executable_fails_fast(self):
        with patch("maru_lang.services.search.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "ripgrep is required"):
                RipgrepSearch()


if __name__ == "__main__":
    unittest.main()
