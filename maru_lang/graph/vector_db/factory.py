"""VectorDB factory - URL-based instance creation.

URL format: {scheme}://{path}/{collection_or_table}
  chroma://data/chroma/maru
  lance://data/lance/maru
  milvus://user:pass@host:port/collection
"""
from pathlib import Path

from maru_lang.configs import get_config
from maru_lang.graph.vector_db.base import VectorDB
from maru_lang.graph.vector_db.chroma import ChromaVectorDB


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
        persist_dir = str((Path.cwd() / path).absolute()) if not Path(path).is_absolute() else path
        return ChromaVectorDB(persist_dir=persist_dir, collection_name=name)

    raise ValueError(f"Unsupported vector_db scheme: {scheme}. Supported: chroma")


def _parse_url(url: str) -> tuple[str, str, str]:
    """Parse a VectorDB URL into (scheme, path, name)."""
    if "://" not in url:
        raise ValueError(f"Invalid vector_db URL: {url}. Expected scheme://path/name")
    scheme, rest = url.split("://", 1)
    parts = rest.rsplit("/", 1)
    if len(parts) == 2:
        return scheme, parts[0], parts[1]
    return scheme, "", parts[0]
