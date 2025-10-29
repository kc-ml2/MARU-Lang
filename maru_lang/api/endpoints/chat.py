import asyncio
from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import ClientDisconnect
from fastapi_pagination.ext.tortoise import apaginate
from fastapi_pagination import Page
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.auth import get_user_with_role, User
from maru_lang.dependencies.chat import get_chat_manager
from maru_lang.pipelines.chat import ChatPipeline
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
from maru_lang.models.chat import ChatHistory
from maru_lang.enums.chat import ChatProcessStep


router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)


@router.post("/request")
async def handle_chat_request(
    request: ChatRequest,
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
    chat_manager: ChatPipeline | None = Depends(get_chat_manager)
) -> ChatResponse:
    try:
        if not chat_manager:
            raise Exception("현재 이용 가능한 AI 서버가 없습니다.")

        # 대화 기록 조회 및 ChatHistory 생성
        conversations = await fetch_conversation_by_user_and_date(
            user=user,
            start_date=request.session_start_time,
            limit=3)

        chat_history = ChatHistory.from_conversations(
            conversations) if conversations else ChatHistory()

        # ChatManager를 사용하여 스트림 처리
        final_result = None
        async for step_result in chat_manager.process_stream(
            question=request.content,
            chat_history=chat_history.to_dict() if chat_history else [],
            user=user
        ):
            step = step_result["step"]

            if step.value == "agent_selection":
                # 에이전트 선택 완료
                selection_data = step_result["data"]

            elif step.value == "agent_execution":
                # 실행 완료
                execution_data = step_result["data"]

            elif step.value == "completed":
                final_result = step_result["data"]
                break

        if not final_result:
            raise HTTPException(
                status_code=500, detail="Failed to generate response")

        answer = final_result["answer"]
        retrieve_documents = final_result.get("documents", [])

        await create_conversation(
            user=user,
            question=request.content,
            answer=answer,
            references=retrieve_documents,
            enhanced_question=request.content,  # Original question as enhanced_question
        )

        return ChatResponse(
            answer=answer,
            references=retrieve_documents
        )

    except asyncio.CancelledError:
        # 클라이언트가 연결을 끊었을 때
        print(f"🔔 Request cancelled by client: {user.email}")
        raise HTTPException(status_code=499, detail="Client disconnected")

    except ClientDisconnect:
        # Starlette의 ClientDisconnect 예외 처리
        print(f"🔔 Client disconnected: {user.email}")
        raise HTTPException(status_code=499, detail="Client disconnected")

    except HTTPException as e:
        # 499 에러는 그대로 전달
        if e.status_code == 499:
            raise e
        # 다른 HTTP 예외는 기존 처리
        raise e

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation", response_model=Page[ConversationResponse])
async def get_conversation(
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    conversations = fetch_conversation_queryset_by_user(user)
    return await apaginate(conversations)
