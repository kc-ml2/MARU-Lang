"""Provider-neutral access to files that must be materialized before use."""
from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Materialization:
    """A provider's prepared action for turning a source into a local file.

    ``write_to`` owns only the provider-specific retrieval/decryption action.
    Temporary-directory lifecycle and result validation remain centralized in
    :func:`materialize_file`.
    """

    provider: str
    write_to: Callable[[Path], None]
    validate: Callable[[Path], bool] = lambda path: path.is_file()


class MaterializationResolver(Protocol):
    """Return a prepared action when this resolver recognizes a source file."""

    def __call__(self, source: Path) -> Materialization | None: ...


def default_resolvers() -> tuple[MaterializationResolver, ...]:
    """Resolvers enabled by default, ordered by precedence."""
    # Lazy import avoids coupling the generic orchestration layer to providers.
    from maru_lang.graph.ingest.materialization.rclone import resolve_rclone_materialization

    return (resolve_rclone_materialization,)


@contextmanager
def materialize_file(
    path: Path,
    *,
    resolvers: Sequence[MaterializationResolver] | None = None,
) -> Iterator[Path]:
    """Yield a local file suitable for any action: hash, upload, copy, or parse.

    Resolvers encapsulate both their matching condition and provider-specific
    action. The first matching resolver writes into a managed temporary path;
    unmatched files are yielded unchanged. Callers therefore need no knowledge
    of zero-byte placeholders, cloud mounts, encrypted stubs, or future source
    types, and temporary files are always removed on context exit.
    """
    source = path.resolve()
    candidates = default_resolvers() if resolvers is None else resolvers
    materialization = next(
        (prepared for resolver in candidates if (prepared := resolver(source)) is not None),
        None,
    )
    if materialization is None:
        yield source
        return

    temp_dir = Path(tempfile.mkdtemp(prefix=f"maru-{materialization.provider}-"))
    destination = temp_dir / source.name
    try:
        materialization.write_to(destination)
        if not materialization.validate(destination):
            raise RuntimeError(
                f"{materialization.provider} produced an invalid file for {source.name}"
            )
        yield destination
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
