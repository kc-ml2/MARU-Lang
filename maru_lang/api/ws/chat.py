"""WebSocket streaming helpers for the chat endpoint."""
import asyncio
import logging
import time
from typing import Callable, Union

from fastapi import WebSocket
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from maru_lang.graph import stream_rag
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session

logger = logging.getLogger(__name__)

# Keepalive: a node like draft/apply_edit is a single long LLM call that emits no
# events until it returns, so the client can sit in silence for many seconds. After
# this much dead air (no graph event) we send a "misc" heartbeat with elapsed time
# so the UI can show "열심히 작업 중입니다…" instead of looking frozen. It only fires
# during silence — while tokens are streaming, events keep resetting the timer.
_HEARTBEAT_INTERVAL_S = 5.0
_HEARTBEAT_MESSAGE = "열심히 작업 중입니다…"


async def stream_and_send(
    websocket: WebSocket,
    message: Union[str, Command],
    team_ids: list[int],
    team_names: list[str],
    graph: CompiledStateGraph,
    config: dict,
    *,
    streamer: Callable = stream_rag,
    user: User | None = None,
    session: Session | None = None,
    function: str | None = None,
    llm_name: str | None = None,
    graph_kwargs: dict | None = None,
    show_thinking: bool = True,
    verbose: bool = False,
) -> bool:
    """Stream a graph's events to a WebSocket client.

    `streamer` is the graph-specific async generator (GraphSpec.streamer):
    stream_rag for chat, stream_doc for doc. `graph_kwargs` carries per-graph
    inputs extracted from the inbound payload (GraphSpec.extract_inputs) — this
    layer forwards them blindly so it stays graph-agnostic. They share one
    keyword surface and a common event vocabulary, so event tuples map to ws
    json generically. Turn 영속화는 각 그래프의 종착 노드가 담당한다 (rag: summarize가
    Conversation 저장; doc: 종착 노드 finalize가 Canvas를 확정하고 세션 이력에
    Conversation 한 줄을 남긴다 — 문서 자체의 영속 산출물은 Canvas/CanvasVersion).

    Returns:
        True if the graph was interrupted (client should send resume), False otherwise.
    """
    if show_thinking:
        await websocket.send_json({"type": "thinking"})

    interrupted = False
    started = time.monotonic()
    stream = streamer(
        message=message,
        team_ids=team_ids,
        team_names=team_names,
        graph=graph,
        config=config,
        function=function,
        session_id=session.id if session else None,
        user_id=user.id if user else None,
        llm_name=llm_name,
        verbose=verbose,
        **(graph_kwargs or {}),
    ).__aiter__()
    # Pull the next event as its own task so we can wait on it WITH a timeout and,
    # on timeout, emit a heartbeat WITHOUT cancelling the pull (cancelling it would
    # abort the running graph). The same task is re-awaited until it resolves.
    next_event = asyncio.ensure_future(stream.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({next_event}, timeout=_HEARTBEAT_INTERVAL_S)
            if not done:
                # Dead air (a long node still running) — reassure the client.
                await websocket.send_json({
                    "type": "misc",
                    "content": _HEARTBEAT_MESSAGE,
                    "elapsed_s": round(time.monotonic() - started, 1),
                })
                continue
            try:
                event_type, event_content = next_event.result()
            except StopAsyncIteration:
                break
            # Queue the next pull before dispatching so the graph keeps advancing
            # while we send (and the heartbeat timer covers the next gap too).
            next_event = asyncio.ensure_future(stream.__anext__())

            if event_type == "token":
                await websocket.send_json({"type": "stream", "content": event_content})
            elif event_type == "node_token":
                # verbose only: an internal node's LLM token, tagged with its node.
                node, content = event_content
                await websocket.send_json({"type": "node_stream", "node": node, "content": content})
            elif event_type == "retrieve":
                await websocket.send_json({"type": "retrieve", "documents": event_content})
            elif event_type == "canvas":
                await websocket.send_json({"type": "canvas", "canvas": event_content})
            elif event_type == "interrupt":
                await websocket.send_json({"type": "interrupt", "content": event_content})
                interrupted = True
    except Exception as e:
        # Surface graph failures instead of silently dropping the stream: log the
        # full traceback server-side, tell the client, and keep the socket open
        # so the conversation survives a single failed turn.
        logger.exception("Chat graph streaming failed (session=%s)", session.id if session else None)
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"응답 생성 중 오류가 발생했습니다: {type(e).__name__}: {e}",
            })
        except Exception:
            pass
        return False
    finally:
        # Don't leak a pending pull on early break/error: cancel + drain it, then
        # close the generator so the graph run is torn down cleanly.
        if not next_event.done():
            next_event.cancel()
            try:
                await next_event
            except BaseException:
                pass
        try:
            await stream.aclose()
        except Exception:
            pass

    if not interrupted:
        await websocket.send_json({"type": "complete"})

    return interrupted
