import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect
from fastapi_pagination.ext.tortoise import apaginate
from fastapi_pagination import Page
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.dependencies.chat import get_chat_pipeline
from maru_lang.pipelines.chat import ChatPipeline
from maru_lang.pipelines.base import PipelineMessage
from maru_lang.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
)
from maru_lang.services.chat import (
    fetch_conversation_queryset_by_user,
    fetch_conversation_by_user_and_date,
    create_conversation,
)
from maru_lang.services.user_group import get_user_accessible_document_groups
from maru_lang.models.chat import ChatHistory
from maru_lang.models.agents import ChatProcess
from maru_lang.enums.chat import ChatProcessStep


router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)


@router.post("/request")
async def handle_chat_request(
    request: ChatRequest,
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
    chat_pipeline: ChatPipeline | None = Depends(get_chat_pipeline)
):
    """
    Handle chat request with streaming response (SSE)

    Returns Server-Sent Events stream with the following event types:

    1. process_step events (with "step" field indicating progress):
       - start: Request processing started
       - agent_selection: Agent selection completed
       - agent_execution: Agent execution completed
       - answer_generation: Final answer generated
       - completed: Request completed

    2. error events:
       - Unrecoverable errors

    Note: Progress messages (info/warning/error from PipelineMessage) are logged
    on the server side and not sent to the client.
    """
    async def event_generator():
        """Generate SSE events from chat pipeline"""
        try:
            # Send initial START event (consistent with ChatProcessStep)
            start_event = {
                "type": "process_step",
                "step": ChatProcessStep.START.value,
                "data": {
                    "question": request.content,
                    "session_start_time": request.session_start_time.isoformat() if request.session_start_time else None,
                    "message": "작업을 시작합니다..."
                }
            }
            yield f"data: {json.dumps(start_event, ensure_ascii=False)}\n\n"

            # 대화 기록 조회 및 ChatHistory 생성
            conversations = await fetch_conversation_by_user_and_date(
                user=user,
                start_date=request.session_start_time,
                limit=3
            )

            chat_history = ChatHistory.from_conversations(
                conversations) if conversations else ChatHistory()

            # Get user's accessible document groups for security
            accessible_groups = await get_user_accessible_document_groups(user.id)

            # Variables to store for final conversation save
            final_answer = None
            final_documents = []
            # Process stream and yield events
            async for step_result in chat_pipeline.process_stream(
                question=request.content,
                chat_history=chat_history,
                forced_groups=accessible_groups
            ):
                # Handle different message types
                if isinstance(step_result, PipelineMessage):
                    # Log progress messages on server side only (not sent to client)
                    message_type = step_result.message_type.value
                    message = step_result.message

                    if message_type == "error":
                        print(f"❌ [Chat Pipeline] {message}")
                    elif message_type == "warning":
                        print(f"⚠️  [Chat Pipeline] {message}")
                    else:  # info
                        print(f"ℹ️  [Chat Pipeline] {message}")

                    # Continue to next iteration without sending to client
                    continue

                elif isinstance(step_result, ChatProcess):
                    step = step_result.step

                    if step == ChatProcessStep.AGENT_SELECTION:
                        # Agent selection completed
                        selection_data = step_result.data
                        event_data = {
                            "type": "process_step",
                            "step": step.value,
                            "data": selection_data.to_dict() if hasattr(selection_data, 'to_dict') else {}
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                    elif step == ChatProcessStep.AGENT_EXECUTION:
                        # Agent execution completed
                        execution_data = step_result.data
                        event_data = {
                            "type": "process_step",
                            "step": step.value,
                            "data": execution_data.to_dict() if hasattr(execution_data, 'to_dict') else {}
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

                    elif step == ChatProcessStep.ANSWER_GENERATION:
                        # Answer generation completed
                        answer = step_result.data
                        final_answer = answer
                        event_data = {
                            "type": "process_step",
                            "step": step.value,
                            "data": {
                                "answer": answer
                            }
                        }
                        yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

            # Save conversation to database
            if final_answer:
                await create_conversation(
                    user=user,
                    question=request.content,
                    answer=final_answer,
                    references=final_documents,
                    enhanced_question=request.content,
                )

            # Send completion event (consistent with process_step format)
            completion_data = {
                "type": "process_step",
                "step": ChatProcessStep.COMPLETED.value,
                "data": {
                    "answer": final_answer,
                    "documents": final_documents
                }
            }
            yield f"data: {json.dumps(completion_data, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            print(f"🔔 Request cancelled by client: {user.email}")
            error_data = {
                "type": "error",
                "message": "Client disconnected"
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

        except ClientDisconnect:
            print(f"🔔 Client disconnected: {user.email}")

        except Exception as e:
            print(f"❌ Error in chat stream: {str(e)}")
            error_data = {
                "type": "error",
                "message": str(e)
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable buffering in nginx
        }
    )


@router.get("/conversation", response_model=Page[ConversationResponse])
async def get_conversation(
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    conversations = fetch_conversation_queryset_by_user(user)
    return await apaginate(conversations)
