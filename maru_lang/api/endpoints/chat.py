import asyncio
import json
from typing import AsyncGenerator, Union
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from maru_lang.services.auth import verify_chat_token
from maru_lang.core.relation_db.models.auth import User
from starlette.websockets import WebSocketState
from maru_lang.dependencies.auth import User
from maru_lang.dependencies.chat import ChatPipelineManager
from maru_lang.pipelines.base import MessageType
from maru_lang.services.team import list_teams_by_user, Team

router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)


@router.websocket("/connect")
async def chat_websocket(websocket: WebSocket):
    """
    WebSocket chat endpoint with chat_token authentication.

    Flow: auth -> message -> stream -> complete
    """
    async def _streaming_message(
        type: str,
        stream: Union[str, AsyncGenerator],
        rate: float = 0.006
    ):
        await websocket.send_json(
            {
                "type": type,
            }
        )
        if isinstance(stream, str):
            if rate > 0:
                for c in stream:
                    await websocket.send_json(
                        {
                            "type": "stream",
                            "content": c
                        }
                    )
                    await asyncio.sleep(rate)
            else:
                try:
                    await websocket.send_json(
                        {
                            "type": "stream",
                            "content": stream
                        }
                    )
                except Exception:
                    print("Failed to send stream message")
        else:
            async for content in stream:
                await websocket.send_json(
                    {
                        "type": "stream",
                        "content": content
                    }
                )
        await websocket.send_json(
            {
                "type": "complete",
            }
        )

    await websocket.accept()

    user: User | None = None
    authenticated = False
    all_user_teams: list[Team] = []
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            # 인증 전: auth 메시지만 허용
            if not authenticated:
                if msg_type != "auth":
                    await _streaming_message(
                        "error",
                        "Authentication required first, before sending messages.")
                    break

                chat_token = data.get("chat_token")
                if not chat_token:
                    await _streaming_message(
                        "error",
                        "chat_token is required when authenticating")
                    break

                user = await verify_chat_token(chat_token)
                if not user:
                    await _streaming_message(
                        "error",
                        "Invalid or expired chat_token")
                    break
                all_user_teams = await list_teams_by_user(user)
                authenticated = True
                continue

            # 인증 후: 메시지 처리
            if msg_type == "message":

                content = data.get("content")
                if not content:
                    await _streaming_message(
                        "error",
                        "message content is required")
                    break
                if not all_user_teams:
                    await _streaming_message(
                        "error",
                        "User does not belong to any team")
                    break
                # TODO pass conversation_id for context-aware chat
                # TODO or something like specification in the message
                chat_pipeline = ChatPipelineManager.create_pipeline()
                if not chat_pipeline:
                    await _streaming_message(
                        "error",
                        "ChatPipeline is not available")
                    break

                # Process stream and yield events
                async for step in chat_pipeline.run(
                    teams=all_user_teams,
                    question=content,
                ):
                    if (
                        step.message_type == MessageType.WARNING or
                        step.message_type == MessageType.ERROR
                    ):
                        await _streaming_message(
                            "error",
                            step.message)
                    elif step.message_type == MessageType.DEBUG:
                        pass  # currently ignore debug messages
                    elif step.message_type == MessageType.RETRIEVE:
                        await _streaming_message(
                            "retrieve",
                            step.message)
                    elif step.message_type == MessageType.INFO:
                        await _streaming_message(
                            "thinking",
                            step.message)
                    elif step.message_type == MessageType.NORMAL:
                        await _streaming_message(
                            "answer",
                            step.message)
            else:
                await _streaming_message(
                    "error",
                    "Unknown message type")
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        await _streaming_message(
            "error",
            f"Server error: {str(e)}")
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
        # Cleanup if needed
