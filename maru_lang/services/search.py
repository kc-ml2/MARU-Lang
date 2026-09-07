"""Selectable deterministic file-search backends."""
from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol, Sequence

from maru_lang.services.filesystem import resolve_within

SearchBackendName = Literal["python", "ripgrep"]
SearchMode = Literal["literal", "regex"]


@dataclass(frozen=True, slots=True)
class TextMatch:
    path: str
    line: int
    byte_column: int
    text: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    backend: SearchBackendName
    results: tuple[dict[str, object], ...]
    truncated: bool


class SearchBackend(Protocol):
    name: SearchBackendName
    version: str

    def find_files(
        self,
        root: Path,
        *,
        path: str = ".",
        name_glob: str | None = None,
        include_globs: Sequence[str] = (),
        exclude_globs: Sequence[str] = (),
        max_results: int = 200,
    ) -> SearchResult: ...

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
    ) -> SearchResult: ...


def _validate_limit(max_results: int) -> None:
    if not 1 <= max_results <= 10_000:
        raise ValueError("max_results must be between 1 and 10000")


def _matches_globs(
    path: str,
    include_globs: Sequence[str],
    exclude_globs: Sequence[str],
) -> bool:
    # Match both the relative path and basename, mirroring common rg glob usage.
    name = PurePosixPath(path).name
    matches = lambda glob: fnmatch.fnmatchcase(path, glob) or fnmatch.fnmatchcase(name, glob)
    return (not include_globs or any(matches(glob) for glob in include_globs)) and not any(
        matches(glob) for glob in exclude_globs
    )


def _search_root(root: Path, path: str) -> tuple[Path, Path]:
    storage_root = root.resolve(strict=True)
    search_root = resolve_within(storage_root, path)
    if not search_root.is_dir():
        raise ValueError("path is not a directory")
    return storage_root, search_root


class PythonSearchBackend:
    """Portable baseline using only Python's standard library."""

    name: SearchBackendName = "python"
    version = "stdlib"

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def _files(
        self,
        root: Path,
        path: str,
        include_globs: Sequence[str],
        exclude_globs: Sequence[str],
    ) -> list[tuple[str, Path]]:
        storage_root, search_root = _search_root(root, path)
        deadline = time.monotonic() + self.timeout_seconds
        files: list[tuple[str, Path]] = []
        pending = [search_root]
        while pending:
            if time.monotonic() > deadline:
                raise TimeoutError("Python file search timed out")
            directory = pending.pop()
            directories: list[Path] = []
            for entry in directory.iterdir():
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    directories.append(entry)
                elif entry.is_file():
                    relative = entry.relative_to(storage_root).as_posix()
                    if _matches_globs(relative, include_globs, exclude_globs):
                        files.append((relative, entry))
            pending.extend(sorted(directories, reverse=True))
        return sorted(files, key=lambda item: item[0])

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
        _validate_limit(max_results)
        found: list[dict[str, object]] = []
        truncated = False
        for relative, _ in self._files(root, path, include_globs, exclude_globs):
            if name_glob is not None and not fnmatch.fnmatchcase(
                PurePosixPath(relative).name, name_glob
            ):
                continue
            if len(found) == max_results:
                truncated = True
                break
            found.append({"path": relative, "type": "file"})
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
        _validate_limit(max_results)
        if not pattern:
            raise ValueError("pattern must not be empty")
        if mode not in ("literal", "regex"):
            raise ValueError("mode must be 'literal' or 'regex'")
        flags = 0 if case_sensitive else re.IGNORECASE
        expression = re.compile(re.escape(pattern) if mode == "literal" else pattern, flags)
        matches: list[TextMatch] = []
        truncated = False
        deadline = time.monotonic() + self.timeout_seconds
        for relative, file_path in self._files(root, path, include_globs, exclude_globs):
            if time.monotonic() > deadline:
                raise TimeoutError("Python text search timed out")
            try:
                with file_path.open("r", encoding="utf-8", errors="strict") as file:
                    for line_number, line in enumerate(file, start=1):
                        text = line.rstrip("\r\n")
                        for match in expression.finditer(text):
                            if len(matches) == max_results:
                                truncated = True
                                break
                            byte_column = len(text[: match.start()].encode("utf-8")) + 1
                            matches.append(TextMatch(relative, line_number, byte_column, text))
                        if truncated:
                            break
            except (UnicodeDecodeError, OSError):
                # Binary, non-UTF-8, and unreadable files are not text-search candidates.
                continue
            if truncated:
                break
        return SearchResult(
            self.name, tuple(asdict(match) for match in matches), truncated
        )


class RipgrepSearchBackend:
    """Fast backend powered by a specific ripgrep executable."""

    name: SearchBackendName = "ripgrep"

    def __init__(self, executable: str, timeout_seconds: float = 10.0):
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        completed = self._run(Path.cwd(), ["--version"])
        if completed.returncode != 0:
            raise RuntimeError("failed to execute ripgrep")
        self.version = completed.stdout.splitlines()[0].strip()

    def _run(self, root: Path, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.executable, *arguments], cwd=root, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=self.timeout_seconds, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            if isinstance(exc, subprocess.TimeoutExpired):
                raise TimeoutError("ripgrep search timed out") from exc
            raise RuntimeError(f"ripgrep executable was not found: {self.executable!r}") from exc

    def find_files(
        self, root: Path, *, path: str = ".", name_glob: str | None = None,
        include_globs: Sequence[str] = (), exclude_globs: Sequence[str] = (),
        max_results: int = 200,
    ) -> SearchResult:
        _validate_limit(max_results)
        storage_root, search_root = _search_root(root, path)
        arguments = ["--no-config", "--files", "--sort", "path", "--hidden", "--no-ignore"]
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
            if name_glob is not None and not fnmatch.fnmatchcase(relative.name, name_glob):
                continue
            if len(found) == max_results:
                truncated = True
                break
            full_path = (PurePosixPath(prefix.as_posix()) / relative).as_posix()
            found.append({"path": full_path, "type": "file"})
        return SearchResult(self.name, tuple(found), truncated)

    def search_text(
        self, root: Path, pattern: str, *, path: str = ".",
        mode: SearchMode = "literal", case_sensitive: bool = True,
        include_globs: Sequence[str] = (), exclude_globs: Sequence[str] = (),
        max_results: int = 200,
    ) -> SearchResult:
        _validate_limit(max_results)
        if not pattern:
            raise ValueError("pattern must not be empty")
        if mode not in ("literal", "regex"):
            raise ValueError("mode must be 'literal' or 'regex'")
        storage_root, search_root = _search_root(root, path)
        arguments = ["--no-config", "--json", "--sort", "path", "--hidden", "--no-ignore"]
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
                matches.append(TextMatch(full_path, data["line_number"], submatch["start"] + 1, text))
            if truncated:
                break
        return SearchResult(self.name, tuple(asdict(match) for match in matches), truncated)


def create_search_backend(
    requested: Literal["auto", "python", "ripgrep"],
    ripgrep_path: str | None = None,
) -> SearchBackend:
    """Resolve `auto` once at application startup; never switch per request."""
    executable = ripgrep_path or shutil.which("rg")
    if requested == "python":
        return PythonSearchBackend()
    if requested == "ripgrep":
        if executable is None:
            raise RuntimeError("MARU_SEARCH_BACKEND=ripgrep but rg was not found")
        return RipgrepSearchBackend(executable)
    if requested == "auto":
        return RipgrepSearchBackend(executable) if executable else PythonSearchBackend()
    raise ValueError(f"unsupported search backend: {requested}")
