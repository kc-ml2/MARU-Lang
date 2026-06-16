"""LLM selection REST endpoints.

사용자가 선택 가능한 LLM 목록을 보고, 본인에게 배정된 LLM을 조회/변경한다.
변경은 다음 메시지부터 적용된다(서버 재기동 불필요).
"""
from fastapi import APIRouter, Depends, HTTPException

from maru_lang.dependencies.auth import get_user
from maru_lang.schemas.llm import LlmResponse, UserLlmResponse, UpdateUserLlmRequest
from maru_lang.services.llm import list_selectable_llms, set_user_llm

router = APIRouter(prefix="/llms", tags=["LLM"])


@router.get("", response_model=list[LlmResponse])
async def list_llms(user=Depends(get_user)):
    """선택 가능한(enabled) LLM 목록."""
    return await list_selectable_llms()


@router.get("/me", response_model=UserLlmResponse)
async def get_my_llm(user=Depends(get_user)):
    """내게 배정된 LLM (미배정이면 null)."""
    await user.fetch_related("assigned_llm")
    assigned = LlmResponse.model_validate(user.assigned_llm) if user.assigned_llm else None
    return UserLlmResponse(assigned_llm=assigned)


@router.put("/me", response_model=UserLlmResponse)
async def set_my_llm(request: UpdateUserLlmRequest, user=Depends(get_user)):
    """내 LLM 변경. enabled LLM만 선택 가능. 다음 메시지부터 적용."""
    try:
        llm = await set_user_llm(user, request.llm_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UserLlmResponse(assigned_llm=LlmResponse.model_validate(llm))
