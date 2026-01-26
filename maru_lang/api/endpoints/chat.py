import asyncio
import json
from typing import AsyncGenerator, Union
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from maru_lang.services.auth import verify_chat_token
from maru_lang.core.relation_db.models.auth import User
from starlette.websockets import WebSocketState
from starlette.requests import ClientDisconnect
from fastapi_pagination.ext.tortoise import apaginate
from fastapi_pagination import Page
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.dependencies.chat import get_chat_pipeline
from maru_lang.pipelines.chat import ChatPipeline
from maru_lang.pipelines.base import PipelineMessage, MessageType
from maru_lang.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    # WSAuthenticatedMessage,
    # WSAuthErrorMessage,
    # WSStartMessage,
    # WSStreamMessage,
    # WSCompleteMessage,
    # WSErrorMessage,
)
from maru_lang.services.chat import (
    fetch_conversation_queryset_by_user,
    fetch_conversation_by_user_and_date,
    create_conversation,
)
from maru_lang.services.team import list_teams_by_user, Team
from maru_lang.models.chat import ChatHistory
from maru_lang.models.agents import ChatProcess, ChatResult
from maru_lang.enums.chat import ChatProcessStep


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
        rate: float = 0.015
    ):
        await websocket.send_json(
            {
                "type": type,
            }
        )
        if isinstance(stream, str):
            for c in stream:
                await websocket.send_json(
                    {
                        "type": "stream",
                        "content": c
                    }
                )
                await asyncio.sleep(rate)
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
                chat_pipeline = get_chat_pipeline()
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
