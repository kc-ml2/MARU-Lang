"""WebSocket streaming helpers for the chat endpoint."""
from typing import Union

from fastapi import WebSocket
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from maru_lang.graph import stream_rag
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.services.chat import create_conversation


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
    question: str | None = None,
    function: str | None = None,
    show_thinking: bool = True,
) -> bool:
    """Stream chat graph events to a WebSocket client.

    When the turn completes (no interrupt) and a question/session is known, the
    completed turn is persisted as a Conversation (with references and feedback).

    Returns:
        True if the graph was interrupted (client should send resume), False otherwise.
    """
    if show_thinking:
        await websocket.send_json({"type": "thinking"})

    interrupted = False
    async for event_type, event_content in stream_rag(
        message=message,
        team_ids=team_ids,
        team_names=team_names,
        graph=graph,
        config=config,
        function=function,
    ):
        if event_type == "token":
            await websocket.send_json({"type": "stream", "content": event_content})
        elif event_type == "retrieve":
            await websocket.send_json({"type": "retrieve", "documents": event_content})
        elif event_type == "interrupt":
            await websocket.send_json({"type": "interrupt", "content": event_content})
            interrupted = True

    if not interrupted:
        if user is not None and question:
            await _persist_turn(graph, config, user, session, question)
        await websocket.send_json({"type": "complete"})

    return interrupted


async def _persist_turn(
    graph: CompiledStateGraph,
    config: dict,
    user: User,
    session: Session | None,
    question: str,
) -> None:
    """Read the final graph state and persist the completed turn."""
    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}

    messages = values.get("messages") or []
    answer = messages[-1].content if messages else ""
    references = values.get("retrieved_documents") or []

    await create_conversation(
        user=user,
        session=session,
        question=question,
        answer=answer,
        references=references,
        feedback_score=values.get("feedback_score"),
        feedback_reason=values.get("feedback_reason"),
    )
