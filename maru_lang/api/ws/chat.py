"""WebSocket streaming helpers for the chat endpoint."""
from typing import Union

from fastapi import WebSocket
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from maru_lang.graph import stream_chat


async def stream_and_send(
    websocket: WebSocket,
    message: Union[str, Command],
    team_ids: list[int],
    team_names: list[str],
    graph: CompiledStateGraph,
    config: dict,
    function: str | None = None,
    show_thinking: bool = True,
) -> bool:
    """Stream chat graph events to a WebSocket client.

    Returns:
        True if the graph was interrupted (client should send resume), False otherwise.
    """
    if show_thinking:
        await websocket.send_json({"type": "thinking"})

    interrupted = False
    async for event_type, event_content in stream_chat(
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
        await websocket.send_json({"type": "complete"})

    return interrupted
