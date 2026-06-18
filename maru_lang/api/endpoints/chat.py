"""Chat WebSocket endpoint."""
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from langgraph.types import Command
from starlette.websockets import WebSocketState

logger = logging.getLogger(__name__)

from maru_lang.services.auth import verify_chat_token
from maru_lang.dependencies.auth import User
from maru_lang.services.team import list_teams_by_user, resolve_user_graph_ids, scope_team_ids
from maru_lang.services.llm import resolve_user_llm_name
from maru_lang.services.session import get_session_for_user
from maru_lang.core.relation_db.models.chat import Session
from maru_lang.graph.router import select_graph
from maru_lang.api.ws.chat import stream_and_send
from maru_lang.core.observability import get_langfuse_handler, langfuse_trace_metadata

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

    On each message the graph_router selects which graph (among the user's teams'
    accessible graphs) handles the request; resume reuses that turn's graph.

    Protocol:
        1. Client sends: {"type": "auth", "chat_token": "...", "session_id": "..."}
        2. Server authenticates + validates session ownership
        3. (Optional) Client sends: {"type": "configure", "function": "legal", ...}
        4. Client sends: {"type": "message", "content": "...", "team_ids": [1, 2]}
           - team_ids is optional; it scopes document search to those teams
             (intersected with the user's own teams). Omit/empty -> all the
             user's teams.
        5. Server streams: {"type": "routed"|"thinking"|"stream"|"retrieve"|"interrupt"|"complete"|"error", ...}
        6. On interrupt, client sends: {"type": "resume", "content": ...}
    """
    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[dict] = []
    all_user_team_ids: list[int] = []
    all_user_team_names: list[int] = []

    active_session: Session | None = None
    allowed_graph_ids: list[str] = []
    active_graph_id: str | None = None  # graph chosen for the current turn
    active_llm_name: str | None = None  # LLM resolved for the current turn (per-user)
    active_team_ids: list[int] = []     # team scope for the current turn
    active_team_names: list[str] = []
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
                allowed_graph_ids = await resolve_user_graph_ids(user)

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

                # Per-message team scoping: the client may send `team_ids` to limit
                # document search to a subset of its teams. Unset/empty -> all of the
                # user's teams. scope_team_ids intersects with the user's own teams so
                # an inaccessible team can't be searched (returns None if none match).
                scoped = scope_team_ids(data.get("team_ids"), all_user_teams)
                if scoped is None:
                    await websocket.send_json({"type": "error", "content": "None of the requested team_ids are accessible"})
                    break
                active_team_ids, active_team_names = scoped

                graphs = getattr(websocket.app.state, "graphs", {}) or {}
                if not graphs or not allowed_graph_ids:
                    await websocket.send_json({"type": "error", "content": "Chat is unavailable (no LLM configured)."})
                    break

                # Per-user LLM: resolve the user's assigned LLM (falls back to the
                # default when unassigned/disabled) and pick that LLM's graph map so
                # every node runs on it. active_llm_name is the *actual* LLM used and
                # is recorded on the turn's Conversation.
                graphs_by_llm = getattr(websocket.app.state, "graphs_by_llm", {}) or {}
                default_llm_name = getattr(websocket.app.state, "default_llm_name", None)
                active_llm_name = await resolve_user_llm_name(user, set(graphs_by_llm), default_llm_name)
                graph_map = graphs_by_llm.get(active_llm_name) or graphs

                # L1 routing: pick which graph handles this request (team-scoped).
                # Route with the user's resolved LLM too, so the whole turn (routing
                # + all graph nodes) runs on one LLM. Falls back to the shared model.
                models_by_llm = getattr(websocket.app.state, "models_by_llm", {}) or {}
                router_model = models_by_llm.get(active_llm_name) or getattr(websocket.app.state, "router_model", None)
                active_graph_id = await select_graph(content, allowed_graph_ids, router_model)
                graph = graph_map.get(active_graph_id)
                if graph is None:
                    await websocket.send_json({"type": "error", "content": "Selected graph is unavailable."})
                    break
                await websocket.send_json({"type": "routed", "graph_id": active_graph_id})

                # One graph run = one thread; fresh thread_id per turn.
                config["configurable"] = {"thread_id": f"{active_session.id}:{uuid.uuid4().hex}"}
                # Per-turn trace metadata. config["metadata"] is inherited by all
                # child runs and lands in LangSmith (configurable only auto-copies
                # scalars, so lists like team_ids must go here explicitly).
                # Resume reuses this turn's config, so it carries over.
                config["metadata"] = {
                    "session_id": active_session.id,
                    "user_id": user.id,
                    "user_name": user.name,
                    "team_ids": active_team_ids,
                    "team_names": active_team_names,
                    "graph_id": active_graph_id,
                    "llm_used": active_llm_name,
                }

                # Langfuse tracing (no-op when disabled): one callback on the run
                # config traces every LLM node in the graph. Set per turn (not
                # appended) so the reused `config` dict can't accumulate handlers.
                handler = get_langfuse_handler()
                if handler is not None:
                    config["callbacks"] = [handler]
                    config["metadata"].update(langfuse_trace_metadata(
                        session_id=active_session.id,
                        user_id=user.id,
                        user_name=user.name,
                        tags=[active_graph_id, active_llm_name],
                    ))

                await stream_and_send(
                    websocket,
                    content,
                    active_team_ids,
                    active_team_names,
                    graph,
                    config,
                    user=user,
                    session=active_session,
                    function=session_function,
                    llm_name=active_llm_name,
                )

            elif msg_type == "resume":
                # Reuse the same per-user LLM graph chosen when the message arrived.
                graphs = getattr(websocket.app.state, "graphs", {}) or {}
                graphs_by_llm = getattr(websocket.app.state, "graphs_by_llm", {}) or {}
                graph_map = graphs_by_llm.get(active_llm_name) or graphs
                graph = graph_map.get(active_graph_id) if active_graph_id else None
                if graph is None or "configurable" not in config:
                    await websocket.send_json({"type": "error", "content": "No active turn to resume"})
                    break

                # Reuse the current turn's thread_id + team scope (set when the message arrived).
                await stream_and_send(
                    websocket,
                    Command(resume=data.get("content")),
                    active_team_ids,
                    active_team_names,
                    graph,
                    config,
                    user=user,
                    session=active_session,
                    llm_name=active_llm_name,
                    show_thinking=False,
                )

            else:
                await websocket.send_json({"type": "error", "content": "Unknown message type"})
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("Chat websocket handler error")
        try:
            await websocket.send_json({"type": "error", "content": f"Server error: {type(e).__name__}: {e}"})
        except Exception:
            pass
    finally:
        # Guard on application_state (did *we* already send a close?), not
        # client_state — otherwise a re-close after the socket is already closed
        # raises 'Cannot call "send" once a close message has been sent.' The
        # try/except absorbs a close racing with a client disconnect.
        if websocket.application_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                pass
