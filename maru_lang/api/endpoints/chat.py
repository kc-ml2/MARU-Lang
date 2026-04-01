"""Chat WebSocket endpoint - LangGraph 기반"""
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessageChunk
from starlette.websockets import WebSocketState

from maru_lang.services.auth import verify_chat_token
from maru_lang.dependencies.auth import User
from maru_lang.dependencies.llm import get_model_with_fallbacks
from maru_lang.graph import create_graph
from maru_lang.services.team import list_teams_by_user, Team

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

# 그래프 인스턴스 (lazy init)
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        model = get_model_with_fallbacks()
        if model is None:
            return None
        _graph = create_graph(model)
    return _graph


@router.websocket("/connect")
async def chat_websocket(websocket: WebSocket):
    """WebSocket chat endpoint.

    Protocol:
        1. Client sends: {"type": "auth", "chat_token": "..."}
        2. Server authenticates, then client can send messages
        3. Client sends: {"type": "message", "content": "..."}
        4. Server streams: {"type": "thinking"|"stream"|"retrieve"|"complete"|"error", ...}
    """
    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[Team] = []
    thread_id: str | None = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # ─── 인증 ─────────────────────────────────
            if not authenticated:
                if msg_type != "auth":
                    await websocket.send_json({"type": "error", "content": "Authentication required"})
                    break

                chat_token = data.get("chat_token")
                if not chat_token:
                    await websocket.send_json({"type": "error", "content": "chat_token is required"})
                    break

                user = await verify_chat_token(chat_token)
                if not user:
                    await websocket.send_json({"type": "error", "content": "Invalid or expired chat_token"})
                    break

                all_user_teams = await list_teams_by_user(user)
                thread_id = f"user-{user.id}"
                authenticated = True
                continue

            # ─── 메시지 처리 ───────────────────────────
            if msg_type == "message":
                content = data.get("content")
                if not content:
                    await websocket.send_json({"type": "error", "content": "message content is required"})
                    break
                if not all_user_teams:
                    await websocket.send_json({"type": "error", "content": "User does not belong to any team"})
                    break

                graph = _get_graph()
                if not graph:
                    await websocket.send_json({"type": "error", "content": "LLM not available"})
                    break

                # LangGraph 입력 구성
                graph_input = {
                    "messages": [HumanMessage(content=content)],
                    "team_ids": [t.id for t in all_user_teams],
                    "team_names": [t.name for t in all_user_teams],
                    "accessible_groups": [],  # TODO: 팀별 문서 그룹 조회
                    "retrieved_documents": [],
                }
                config = {"configurable": {"thread_id": thread_id}}

                # 스트리밍
                await websocket.send_json({"type": "thinking"})

                async for event, metadata in graph.astream(
                    graph_input,
                    config=config,
                    stream_mode="messages",
                ):
                    # LLM 토큰 스트리밍
                    if isinstance(event, AIMessageChunk) and event.content:
                        await websocket.send_json({
                            "type": "stream",
                            "content": event.content,
                        })

                    # Tool 호출 결과 (검색 결과 등)
                    if hasattr(event, "name") and event.name == "knowledge_search":
                        await websocket.send_json({
                            "type": "retrieve",
                            "content": event.content if hasattr(event, "content") else "",
                        })

                await websocket.send_json({"type": "complete"})

            else:
                await websocket.send_json({"type": "error", "content": "Unknown message type"})
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": f"Server error: {str(e)}"})
        except Exception:
            pass
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
