"""Deterministic filesystem search powered exclusively by ripgrep."""
from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

from maru_lang.services.filesystem import resolve_within

SearchMode = Literal["literal", "regex"]


@dataclass(frozen=True, slots=True)
class TextMatch:
    path: str
    line: int
    byte_column: int
    text: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    backend: Literal["ripgrep"]
    results: tuple[dict[str, object], ...]
    truncated: bool


class RipgrepSearch:
    """The required, process-wide filesystem search engine."""

    name = "ripgrep"

    def __init__(self, executable: str | None = None, timeout_seconds: float = 10.0):
        resolved = executable or shutil.which("rg")
        if resolved is None:
            raise RuntimeError(
                "ripgrep is required but rg was not found; install ripgrep or set "
                "MARU_RIPGREP_PATH"
            )
        self.executable = resolved
        self.timeout_seconds = timeout_seconds
        completed = self._run(Path.cwd(), ["--version"])
        if completed.returncode != 0:
            raise RuntimeError("failed to execute ripgrep")
        self.version = completed.stdout.splitlines()[0].strip()

    def _run(
        self, root: Path, arguments: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.executable, *arguments],
                cwd=root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"ripgrep executable was not found: {self.executable!r}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("ripgrep search timed out") from exc

    @staticmethod
    def _validate_limit(max_results: int) -> None:
        if not 1 <= max_results <= 10_000:
            raise ValueError("max_results must be between 1 and 10000")

    @staticmethod
    def _roots(root: Path, path: str) -> tuple[Path, Path]:
        storage_root = root.resolve(strict=True)
        search_root = resolve_within(storage_root, path)
        if not search_root.is_dir():
            raise ValueError("path is not a directory")
        return storage_root, search_root

    def find_files(
        self,
        root: Path,
        *,
        path: str = ".",
        name_glob: str | None = None,
        include_globs: Sequence[str] = (),
        exclude_globs: Sequence[str] = (),
        max_results: int = 200,
    ) -> SearchResult:
        self._validate_limit(max_results)
        storage_root, search_root = self._roots(root, path)
        arguments = [
            "--no-config", "--files", "--sort", "path", "--hidden", "--no-ignore",
        ]
        for glob in include_globs:
            arguments.extend(("--glob", glob))
        for glob in exclude_globs:
            arguments.extend(("--glob", f"!{glob}"))
        arguments.append(".")
        completed = self._run(search_root, arguments)
        if completed.returncode not in (0, 1):
            raise RuntimeError(completed.stderr.strip() or "ripgrep file search failed")

        prefix = search_root.relative_to(storage_root)
        found: list[dict[str, object]] = []
        truncated = False
        for raw_path in completed.stdout.splitlines():
            relative = PurePosixPath(raw_path.removeprefix("./"))
            if name_glob is not None and not fnmatch.fnmatchcase(
                relative.name, name_glob
            ):
                continue
            if len(found) == max_results:
                truncated = True
                break
            full_path = (PurePosixPath(prefix.as_posix()) / relative).as_posix()
            found.append({"path": full_path, "type": "file"})
        return SearchResult(self.name, tuple(found), truncated)

    def search_text(
        self,
        root: Path,
        pattern: str,
        *,
        path: str = ".",
        mode: SearchMode = "literal",
        case_sensitive: bool = True,
        include_globs: Sequence[str] = (),
        exclude_globs: Sequence[str] = (),
        max_results: int = 200,
    ) -> SearchResult:
        self._validate_limit(max_results)
        if not pattern:
            raise ValueError("pattern must not be empty")
        if mode not in ("literal", "regex"):
            raise ValueError("mode must be 'literal' or 'regex'")
        storage_root, search_root = self._roots(root, path)
        arguments = [
            "--no-config", "--json", "--sort", "path", "--hidden", "--no-ignore",
        ]
        if mode == "literal":
            arguments.append("--fixed-strings")
        if not case_sensitive:
            arguments.append("--ignore-case")
        for glob in include_globs:
            arguments.extend(("--glob", glob))
        for glob in exclude_globs:
            arguments.extend(("--glob", f"!{glob}"))
        arguments.extend(("--", pattern, "."))
        completed = self._run(search_root, arguments)
        if completed.returncode not in (0, 1):
            raise ValueError(completed.stderr.strip() or "ripgrep text search failed")

        prefix = search_root.relative_to(storage_root)
        matches: list[TextMatch] = []
        truncated = False
        for output_line in completed.stdout.splitlines():
            event = json.loads(output_line)
            if event.get("type") != "match":
                continue
            data = event["data"]
            relative = PurePosixPath(data["path"]["text"].removeprefix("./"))
            full_path = (PurePosixPath(prefix.as_posix()) / relative).as_posix()
            text = data["lines"]["text"].rstrip("\r\n")
            for submatch in data["submatches"]:
                if len(matches) == max_results:
                    truncated = True
                    break
                matches.append(
                    TextMatch(
                        full_path,
                        data["line_number"],
                        submatch["start"] + 1,
                        text,
                    )
                )
            if truncated:
                break
        return SearchResult(
            self.name, tuple(asdict(match) for match in matches), truncated
        )
