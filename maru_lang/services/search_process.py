"""Bounded streaming subprocess output for ripgrep (POSIX servers)."""
import os
import selectors
import subprocess
import time
from collections.abc import Iterator, Sequence
from pathlib import Path


class OutputLimitReached(Exception):
    """The output budget was exhausted; callers should mark partial results."""


def records(
    executable: str, root: Path, arguments: Sequence[str], *, separator: bytes,
    timeout: float, max_output_bytes: int,
) -> Iterator[bytes]:
    """Drain both pipes, bound buffering, and reap the child even on early close."""
    try:
        process = subprocess.Popen(
            [executable, *arguments], cwd=root, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"ripgrep executable was not found: {executable!r}") from exc
    deadline = time.monotonic() + timeout
    pending = bytearray()
    errors = bytearray()
    total = 0
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("ripgrep search timed out")
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    if total > max_output_bytes:
                        raise OutputLimitReached
                    if key.data == 'stderr':
                        errors.extend(chunk[:max(0, 8192 - len(errors))])
                        continue
                    pending.extend(chunk)
                    while True:
                        end = pending.find(separator)
                        if end < 0:
                            break
                        record = bytes(pending[:end])
                        del pending[:end + len(separator)]
                        yield record
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("ripgrep search timed out")
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError("ripgrep search timed out") from exc
            if code not in (0, 1):
                raise ValueError(errors.decode('utf-8', errors='replace').strip()
                                 or 'ripgrep search failed')
            if pending:
                yield bytes(pending)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()
