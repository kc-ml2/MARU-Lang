"""Chat WebSocket endpoint."""
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langgraph.types import Command
from starlette.websockets import WebSocketState

from maru_lang.services.auth import verify_chat_token
from maru_lang.dependencies.auth import User
from maru_lang.graph import create_rag_graph
from maru_lang.services.team import list_teams_by_user
from maru_lang.services.session import get_session_for_user
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.api.ws.chat import stream_and_send

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)


@router.websocket("/connect")
async def chat_websocket(websocket: WebSocket):
    """WebSocket chat endpoint.

    The session lifecycle (create/list/delete) is handled by a separate REST API.
    The client always supplies an existing session_id at auth time; the socket
    validates ownership and persists each completed turn under that session.

    Each message starts a fresh LangGraph thread (one graph run = one thread),
    reused only across that turn's interrupt/resume. Completed turns are stored
    as Conversation rows grouped by the session.

    Protocol:
        1. Client sends: {"type": "auth", "chat_token": "...", "session_id": "..."}
        2. Server authenticates + validates session ownership
        3. (Optional) Client sends: {"type": "configure", "function": "legal", ...}
        4. Client sends: {"type": "message", "content": "..."}
        5. Server streams: {"type": "thinking"|"stream"|"retrieve"|"interrupt"|"complete"|"error", ...}
        6. On interrupt, client sends: {"type": "resume", "content": ...}
    """
    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[dict] = []
    all_user_team_ids: list[int] = []
    all_user_team_names: list[int] = []

    active_session: Session | None = None
    pending_question: str | None = None
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

                session_id = data.get("session_id")
                if not session_id:
                    await websocket.send_json({"type": "error", "content": "session_id is required"})
                    break

                active_session = await get_session_for_user(session_id, user)
                if active_session is None:
                    await websocket.send_json({"type": "error", "content": "Invalid or unauthorized session_id"})
                    break

                all_user_teams = await list_teams_by_user(user)
                all_user_team_ids = [t["id"] for t in all_user_teams]
                all_user_team_names = [t["name"] for t in all_user_teams]

                authenticated = True
                await websocket.send_json({"type": "authenticated", "session_id": active_session.id})
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
                        checkpointer = getattr(websocket.app.state, "checkpointer", None)
                        graph = create_rag_graph(checkpointer=checkpointer)
                    except RuntimeError as e:
                        await websocket.send_json({"type": "error", "content": str(e)})
                        break

                # One graph run = one thread; fresh thread_id per turn.
                config["configurable"] = {"thread_id": f"{active_session.id}:{uuid.uuid4().hex}"}
                pending_question = content

                interrupted = await stream_and_send(
                    websocket,
                    content,
                    all_user_team_ids,
                    all_user_team_names,
                    graph,
                    config,
                    user=user,
                    session=active_session,
                    question=content,
                    function=session_function,
                )
                if not interrupted:
                    pending_question = None

            elif msg_type == "resume":
                if graph is None or "configurable" not in config:
                    await websocket.send_json({"type": "error", "content": "No active turn to resume"})
                    break

                # Reuse the current turn's thread_id (set when the message arrived).
                interrupted = await stream_and_send(
                    websocket,
                    Command(resume=data.get("content")),
                    all_user_team_ids,
                    all_user_team_names,
                    graph,
                    config,
                    user=user,
                    session=active_session,
                    question=pending_question,
                    show_thinking=False,
                )
                if not interrupted:
                    pending_question = None

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
