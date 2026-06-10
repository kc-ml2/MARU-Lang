"""VectorDB factory - URL-based instance creation.

URL format: {scheme}://{path}/{collection_or_table}
  chroma://data/chroma/maru                 # embedded (local files, single process)
  chroma+http://localhost:8000/maru         # server mode (shared; needed for the queue)
  chroma+https://chroma.internal:8000/maru  # server mode over TLS
  lance://data/lance/maru
  milvus://user:pass@host:port/collection
"""
from pathlib import Path

from maru_lang.configs import get_config
from maru_lang.core.vector_db.base import VectorDB
from maru_lang.core.vector_db.chroma import ChromaVectorDB


def get_vector_db(url: str | None = None) -> VectorDB:
    """Create a VectorDB instance from a URL.

    Args:
        url: VectorDB URL. If None, reads from config.

    Returns:
        VectorDB instance.
    """
    if url is None:
        cfg = get_config()
        url = cfg.vector_db_url

    scheme, path, name = _parse_url(url)

    if scheme == "chroma":
        # Embedded: path is a local directory.
        persist_dir = str((Path.cwd() / path).absolute()) if not Path(path).is_absolute() else path
        return ChromaVectorDB(collection_name=name, persist_dir=persist_dir)

    if scheme in ("chroma+http", "chroma+https"):
        # Server mode: path is host[:port]. Both the API and the ARQ worker point
        # at the same Chroma server, so the worker's writes are visible to the API
        # (unlike embedded Chroma) — this is the multi-process / queue setup.
        host, port = _parse_host_port(path)
        return ChromaVectorDB(
            collection_name=name, host=host, port=port, ssl=(scheme == "chroma+https"),
        )

    raise ValueError(
        f"Unsupported vector_db scheme: {scheme}. "
        f"Supported: chroma, chroma+http, chroma+https"
    )


def _parse_url(url: str) -> tuple[str, str, str]:
    """Parse a VectorDB URL into (scheme, path, name)."""
    if "://" not in url:
        raise ValueError(f"Invalid vector_db URL: {url}. Expected scheme://path/name")
    scheme, rest = url.split("://", 1)
    parts = rest.rsplit("/", 1)
    if len(parts) == 2:
        return scheme, parts[0], parts[1]
    return scheme, "", parts[0]


def _parse_host_port(authority: str) -> tuple[str, int]:
    """Split "host:port" into (host, port); default port 8000 when omitted."""
    if ":" in authority:
        host, port_s = authority.rsplit(":", 1)
        return host, int(port_s)
    return authority, 8000
