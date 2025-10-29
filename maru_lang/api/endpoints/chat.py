import asyncio
from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import ClientDisconnect
from fastapi_pagination.ext.tortoise import apaginate
from fastapi_pagination import Page
from maru_lang.enums.auth import UserRoleCode
from maru_lang.dependencies.langfuse import get_langfuse_context, LangfuseContext
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
    chat_manager: ChatPipeline | None = Depends(get_chat_manager),
    context: LangfuseContext = Depends(get_langfuse_context),
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
            user=user,
            context=context
        ):
            step = step_result["step"]

            if step.value == "agent_selection":
                # Langfuse에 에이전트 선택 기록
                selection_data = step_result["data"]
                context.update_metadata(
                    selected_tools=selection_data.get("selected_agents", []),
                    agent_selection_reasoning=selection_data.get("reasoning", "")
                )

            elif step.value == "agent_execution":
                # Langfuse에 실행 결과 기록
                execution_data = step_result["data"]
                context.update_metadata(
                    agents_executed=list(execution_data.get("agent_results", {}).keys()),
                    success_count=sum(1 for result in execution_data.get("agent_results", {}).values()
                                    if result.get("success", False))
                )

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

        # Langfuse 출력 업데이트
        context.update_trace(
            output={
                # 답변 길이 제한
                "answer": answer[:500] if answer else "No response generated",
                "references_count": len(retrieve_documents),
                "has_references": bool(retrieve_documents)
            }
        )

        context.update_metadata(
            response_length=len(answer) if answer else 0,
            reference_documents=[
                {
                    "name": doc.metadata.get('document_name', 'Unknown'),
                    "score": doc.metadata.get('score', 0)
                }
                for doc in retrieve_documents[:3]  # 상위 3개만
            ] if retrieve_documents else []
        )

        return ChatResponse(
            answer=answer,
            references=retrieve_documents
        )

    except asyncio.CancelledError:
        # 클라이언트가 연결을 끊었을 때
        print(f"🔔 Request cancelled by client: {user.email}")
        context.update_span(
            level="WARNING",
            status_message="Request cancelled by client"
        )
        raise HTTPException(status_code=499, detail="Client disconnected")

    except ClientDisconnect:
        # Starlette의 ClientDisconnect 예외 처리
        print(f"🔔 Client disconnected: {user.email}")
        context.update_span(
            level="WARNING",
            status_message="Client disconnected"
        )
        raise HTTPException(status_code=499, detail="Client disconnected")

    except HTTPException as e:
        # 499 에러는 그대로 전달
        if e.status_code == 499:
            raise e
        # 다른 HTTP 예외는 기존 처리
        context.update_span(
            level="ERROR",
            status_message=f"HTTP Error: {str(e)}"
        )
        raise e

    except Exception as e:
        context.update_span(
            level="ERROR",
            status_message=f"답변 생성 실패: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversation", response_model=Page[ConversationResponse])
async def get_conversation(
    user: User = Depends(get_user_with_role(UserRoleCode.EDITOR)),
):
    conversations = fetch_conversation_queryset_by_user(user)
    return await apaginate(conversations)
