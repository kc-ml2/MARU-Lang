"""Chat WebSocket endpoint."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from maru_lang.services.auth import verify_chat_token
from maru_lang.dependencies.auth import User
from maru_lang.graph import create_chat_graph, stream_chat
from maru_lang.services.team import list_teams_by_user, Team

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
        3. Client sends: {"type": "message", "content": "..."}
        4. Server streams: {"type": "thinking"|"stream"|"retrieve"|"complete"|"error", ...}
    """
    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[Team] = []
    thread_id: str | None = None
    graph = None

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

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

                # Create graph after auth (once per connection)
                try:
                    graph = create_chat_graph()
                except RuntimeError as e:
                    await websocket.send_json({"type": "error", "content": str(e)})
                    break
                continue

            if msg_type == "message":
                content = data.get("content")
                if not content:
                    await websocket.send_json({"type": "error", "content": "message content is required"})
                    break
                if not all_user_teams:
                    await websocket.send_json({"type": "error", "content": "User does not belong to any team"})
                    break

                config = {"configurable": {"thread_id": thread_id}}

                await websocket.send_json({"type": "thinking"})

                async for event_type, event_content in stream_chat(
                    message=content,
                    team_ids=[t["id"] for t in all_user_teams],
                    team_names=[t["name"] for t in all_user_teams],
                    graph=graph,
                    config=config,
                ):
                    if event_type == "token":
                        await websocket.send_json({
                            "type": "stream",
                            "content": event_content,
                        })
                    elif event_type == "retrieve":
                        await websocket.send_json({
                            "type": "retrieve",
                            "documents": event_content,
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
