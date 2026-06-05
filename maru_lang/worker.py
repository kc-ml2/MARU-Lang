"""ARQ worker — runs document embedding/ingest off the API process.

Activated by `task_queue_enabled: true` + `redis_url` in maru_config.yaml.
Run as a separate process alongside the API:

    maru worker                         # convenience wrapper
    arq maru_lang.worker.WorkerSettings # equivalent

The embedding model loads once in this process (GPU-bound if available), so the
API process never pays the embedding cost and the GPU is held by one place.
"""
import logging

from arq.connections import RedisSettings

from maru_lang.configs import get_config
from maru_lang.core.relation_db.connection import orm_context
from maru_lang.graph.ingest.embedder import get_embeddings

logger = logging.getLogger(__name__)


async def ingest_document_task(ctx, document_id: str, team_id: int) -> None:
    """Embed one uploaded document.

    Only JSON-serializable args cross the Redis boundary, so we pass the
    document_id (not the ORM object) and re-fetch it inside the worker.
    """
    from maru_lang.core.relation_db.models.documents import Document
    from maru_lang.services.ingest import run_ingest_for_document

    doc = await Document.get_or_none(id=document_id)
    if doc is None:
        logger.warning(
            "ingest_document_task: document %s no longer exists, skipping", document_id
        )
        return
    await run_ingest_for_document(doc, team_id)


async def _on_startup(ctx) -> None:
    """Bring up the worker process: ORM + preloaded embedding model."""
    cfg = get_config()
    cm = orm_context()
    await cm.__aenter__()
    ctx["_orm_cm"] = cm
    logger.info("Worker ORM initialized")

    device = cfg.resolve_ingest_embedding_device()
    get_embeddings(cfg.embedding_model, device)
    logger.info(
        "Worker embedding model loaded: %s (device=%s)",
        cfg.embedding_model,
        device or "auto",
    )


async def _on_shutdown(ctx) -> None:
    cm = ctx.get("_orm_cm")
    if cm is not None:
        # orm_context's finally closes the Tortoise connections.
        await cm.__aexit__(None, None, None)


_cfg = get_config()
if not _cfg.redis_url:
    raise RuntimeError(
        "maru worker requires redis_url in maru_config.yaml "
        "(set task_queue_enabled: true and redis_url)."
    )


class WorkerSettings:
    """ARQ entrypoint: `arq maru_lang.worker.WorkerSettings`."""

    functions = [ingest_document_task]
    redis_settings = RedisSettings.from_dsn(_cfg.redis_url)
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 2   # embedding is GPU/CPU-bound; keep per-worker concurrency low
    max_tries = 3  # transient failures retried with ARQ's exponential backoff
