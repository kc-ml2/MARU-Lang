"""Chat WebSocket endpoint."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langgraph.types import Command
from starlette.websockets import WebSocketState

from maru_lang.services.auth import verify_chat_token
from maru_lang.dependencies.auth import User
from maru_lang.graph import create_chat_graph
from maru_lang.services.team import list_teams_by_user
from maru_lang.api.ws.chat import stream_and_send

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


@router.websocket("/connect")
async def chat_websocket(websocket: WebSocket):
    """WebSocket chat endpoint.

    Protocol:
        1. Client sends: {"type": "auth", "chat_token": "..."}
        2. Server authenticates, then client can send messages
        3. (Optional) Client sends: {"type": "configure", "function": "legal", ...}
        4. Client sends: {"type": "message", "content": "..."}
        5. Server streams: {"type": "thinking"|"stream"|"retrieve"|"interrupt"|"complete"|"error", ...}
        6. On interrupt, client sends: {"type": "resume", "value": ...}
    """
    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[dict] = []
    all_user_team_ids: list[int] = []
    all_user_team_names: list[int] = []

    thread_id: str | None = None
    graph = None
    config = {}
    session_function: str | None = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.pop("type", None)

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
                all_user_team_ids = [t["id"] for t in all_user_teams]
                all_user_team_names = [t["name"] for t in all_user_teams]
                
                thread_id = f"user-{user.id}"
                config.update({"configurable": {"thread_id": thread_id}})
                authenticated = True
                continue

            if msg_type == "configure":
                session_function = data.pop("function", session_function)
                config.update(**data)
                await websocket.send_json({"type": "configured"})
                continue

            if msg_type == "message":
                content = data.get("content")
                if not content:
                    await websocket.send_json({"type": "error", "content": "message content is required"})
                    break
                if not all_user_teams:
                    await websocket.send_json({"type": "error", "content": "User does not belong to any team"})
                    break

                if graph is None:
                    try:
                        graph = create_chat_graph()
                    except RuntimeError as e:
                        await websocket.send_json({"type": "error", "content": str(e)})
                        break

                await stream_and_send(
                    websocket,
                    content,
                    all_user_team_ids,
                    all_user_team_names,
                    graph,
                    config,
                    function=session_function,
                )

            elif msg_type == "resume":
                if graph is None:
                    await websocket.send_json({"type": "error", "content": "No active graph to resume"})
                    break
                await stream_and_send(
                    websocket,
                    Command(resume=data.get("content")),
                    all_user_team_ids,
                    all_user_team_names,
                    graph,
                    config,
                    show_thinking=False,
                )

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
