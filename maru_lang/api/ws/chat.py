"""WebSocket streaming helpers for the chat endpoint."""
import logging
from typing import Union

from fastapi import WebSocket
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from maru_lang.graph import stream_rag
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session

logger = logging.getLogger(__name__)


async def stream_and_send(
    websocket: WebSocket,
    message: Union[str, Command],
    team_ids: list[int],
    team_names: list[str],
    graph: CompiledStateGraph,
    config: dict,
    *,
    user: User | None = None,
    session: Session | None = None,
    function: str | None = None,
    llm_name: str | None = None,
    show_thinking: bool = True,
) -> bool:
    """Stream chat graph events to a WebSocket client.

    Turn 영속화(Conversation 생성 + Session.summary 갱신)는 그래프의 summarize
    종착 노드가 담당한다. 여기서는 스트리밍만 한다.

    Returns:
        True if the graph was interrupted (client should send resume), False otherwise.
    """
    if show_thinking:
        await websocket.send_json({"type": "thinking"})

    interrupted = False
    try:
        async for event_type, event_content in stream_rag(
            message=message,
            team_ids=team_ids,
            team_names=team_names,
            graph=graph,
            config=config,
            function=function,
            session_id=session.id if session else None,
            user_id=user.id if user else None,
            llm_name=llm_name,
        ):
            if event_type == "token":
                await websocket.send_json({"type": "stream", "content": event_content})
            elif event_type == "retrieve":
                await websocket.send_json({"type": "retrieve", "documents": event_content})
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

    if not interrupted:
        await websocket.send_json({"type": "complete"})

    return interrupted
