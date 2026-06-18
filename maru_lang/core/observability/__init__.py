"""Langfuse observability — LLM tracing wired to maru_config.

One injection point: attach `get_langfuse_handler()` to a run's
`config["callbacks"]` and LangGraph propagates it to every child LLM call, so
the whole chat graph (route/intent/keywords/generate/summarize/...) is traced.

All Langfuse SDK (v3) specifics live here; the rest of the codebase only sees
`get_langfuse_handler()` (-> handler or None) and `flush_langfuse()`.
"""
import logging
from typing import Optional

from maru_lang.configs import get_config

logger = logging.getLogger(__name__)

# Cache the handler across requests. A single v3 CallbackHandler is stateless
# w.r.t. traces (trace context is derived per-run from the callback metadata),
# so it is safe to reuse for every connection.
_handler = None
_initialized = False


def get_langfuse_handler():
    """Return a cached Langfuse CallbackHandler, or None when disabled.

    Initializes the global Langfuse client (from config keys) on first call.
    Returns None — never raises — if Langfuse is off, keys are missing, or the
    package isn't installed, so callers can inject unconditionally.
    """
    global _handler, _initialized
    if _initialized:
        return _handler
    _initialized = True

    cfg = get_config().langfuse
    if not cfg.is_active:
        return None

    try:
        from langfuse import Langfuse
        from langfuse.langchain import CallbackHandler
    except ImportError as e:
        # Surface the real cause: besides 'langfuse' itself, its langchain
        # integration imports the umbrella 'langchain' package (for version
        # detection), which a langchain-core-only install lacks.
        logger.warning(
            "langfuse.enabled=true but the Langfuse langchain integration is "
            "unavailable (%s). Install the observability deps "
            "(`pip install langfuse langchain`) or set langfuse.enabled=false.",
            e,
        )
        return None

    # Configures the process-global Langfuse singleton that CallbackHandler reads.
    Langfuse(public_key=cfg.public_key, secret_key=cfg.secret_key, host=cfg.host)
    _handler = CallbackHandler()
    logger.info("Langfuse tracing enabled (host=%s)", cfg.host)
    return _handler


def flush_langfuse() -> None:
    """Flush buffered traces (call on shutdown). No-op when disabled."""
    if not _initialized or _handler is None:
        return
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:  # never let observability break shutdown
        logger.debug("Langfuse flush failed", exc_info=True)


def langfuse_trace_metadata(
    *,
    session_id: Optional[str],
    user_id,
    user_name: Optional[str] = None,
    tags: Optional[list] = None,
) -> dict:
    """Map app identifiers to the metadata keys Langfuse v3 reads off a run.

    Merge the result into `config["metadata"]` so traces are grouped by session
    and attributed to a user in the Langfuse UI.

    Langfuse has no separate "name" field — the value shown in the Users tab is
    `langfuse_user_id`. To surface the human name there while keeping the id
    unique (names collide), we display it as `name (#id)` when a name is given.
    """
    meta: dict = {}
    if session_id:
        meta["langfuse_session_id"] = session_id
    if user_id is not None:
        name = (user_name or "").strip()
        meta["langfuse_user_id"] = f"{name} (#{user_id})" if name else str(user_id)
    clean_tags = [t for t in (tags or []) if t]
    if clean_tags:
        meta["langfuse_tags"] = clean_tags
    return meta
