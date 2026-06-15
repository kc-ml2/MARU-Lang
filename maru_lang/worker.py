"""ARQ worker — runs document embedding/ingest off the API process.

Activated by `task_queue_enabled: true` + `redis_url` in maru_config.yaml.
Run as a separate process alongside the API:

    maru worker                         # convenience wrapper
    arq maru_lang.worker.WorkerSettings # equivalent

The embedding model loads once in this process (GPU-bound if available), so the
API process never pays the embedding cost and the GPU is held by one place.
"""
import logging

from arq import func
from arq.connections import RedisSettings

from maru_lang.configs import get_config
from maru_lang.constants import INGEST_TASK_NAME
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


def _configure_logging(cfg) -> None:
    """Make maru_lang.* logs visible in the worker process.

    The worker runs as `arq maru_lang.worker.WorkerSettings`, and ARQ only
    configures its own `arq` logger — root/`maru_lang` get no handler, so our
    INFO logs (parser routing, KorDoc command, etc.) are dropped and only
    WARNING+ reaches the journal. Attach a root handler and set the maru_lang
    level from config.server.log_level (default "info").
    """
    level = getattr(logging, str(cfg.server.log_level).upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("maru_lang").setLevel(level)


async def _on_startup(ctx) -> None:
    """Bring up the worker process: ORM + preloaded embedding model."""
    cfg = get_config()
    _configure_logging(cfg)
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

    # Backstop for the cooperative-cancel state machine: finalize any documents
    # left in DELETING by a worker that crashed mid-cleanup or a delete that
    # raced a just-finished job.
    from maru_lang.services.ingest import reconcile_deletions
    n = await reconcile_deletions()
    if n:
        logger.info("Worker reconcile: finalized %d DELETING document(s)", n)


async def _on_shutdown(ctx) -> None:
    # Tear down the persistent KorDoc MCP session (no-op if it was never used).
    from maru_lang.graph.ingest.loader.kordoc_mcp import close_kordoc_client
    await close_kordoc_client()

    cm = ctx.get("_orm_cm")
    if cm is not None:
        # orm_context's finally closes the Tortoise connections.
        await cm.__aexit__(None, None, None)


def _worker_redis_settings() -> RedisSettings:
    """RedisSettings from config; defaults to localhost when redis_url is unset.

    The supported launch paths (`maru worker`, `maru run/serve --worker`) already
    fail fast when the queue is off, so this just keeps the module importable
    (e.g. for tests) instead of raising at import time.
    """
    cfg = get_config()
    return RedisSettings.from_dsn(cfg.redis_url) if cfg.redis_url else RedisSettings()


class WorkerSettings:
    """ARQ entrypoint: `arq maru_lang.worker.WorkerSettings`."""

    # Register with an explicit name tied to INGEST_TASK_NAME so the enqueue
    # side (api/endpoints/ingest.py) and the worker can't drift apart.
    functions = [func(ingest_document_task, name=INGEST_TASK_NAME)]
    redis_settings = _worker_redis_settings()
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 2   # embedding is GPU/CPU-bound; keep per-worker concurrency low
    max_tries = 3  # transient failures retried with ARQ's exponential backoff
