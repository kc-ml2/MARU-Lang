from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from maru_lang.dependencies.auth import get_user
from maru_lang.dependencies.email import EmailService, get_email_service_dependency
from maru_lang.schemas.team import (
    CreateTeamRequest,
    InviteMemberRequest,
    TeamSummaryResponse,
    TeamDetailResponse,
    TeamMemberResponse,
    GraphInfoResponse,
    SetTeamGraphsRequest,
    TeamGraphsResponse,
)
from maru_lang.services.team import (
    list_teams_by_user,
    get_team_detail,
    create_team,
    invite_member,
    remove_member,
    set_team_allowed_graphs,
    list_registerable_graphs,
)

router = APIRouter(prefix="/teams", tags=["Teams"])


@router.get("", response_model=list[TeamSummaryResponse])
async def get_my_teams(user=Depends(get_user)):
    """로그인한 사용자가 속한 팀 목록 조회"""
    return await list_teams_by_user(user)


@router.get("/available-graphs", response_model=list[GraphInfoResponse])
async def get_available_graphs(user=Depends(get_user)):
    """팀에 설정 가능한 등록된 그래프 목록 (id + 설명)"""
    return list_registerable_graphs()


@router.put("/{team_id}/graphs", response_model=TeamGraphsResponse)
async def set_team_graphs(team_id: int, request: SetTeamGraphsRequest, user=Depends(get_user)):
    """팀의 사용 가능 그래프 설정 (팀 admin만 가능; []이면 기본값으로 리셋)"""
    try:
        allowed = await set_team_allowed_graphs(team_id, request.graphs, user)
        return TeamGraphsResponse(id=team_id, allowed_graphs=allowed)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(team_id: int, user=Depends(get_user)):
    """팀 상세 조회 (멤버 + 폴더)"""
    try:
        return await get_team_detail(team_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("", response_model=TeamSummaryResponse, status_code=201)
async def create_new_team(request: CreateTeamRequest, user=Depends(get_user)):
    """새 팀 생성 (생성자는 자동 admin)"""
    try:
        team = await create_team(request.name, user, request.description)
        return TeamSummaryResponse(
            id=team.id, name=team.name, description=team.description, role="admin"
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=201)
async def invite_team_member(
    team_id: int,
    request: InviteMemberRequest,
    user=Depends(get_user),
    email_service: Optional[EmailService] = Depends(get_email_service_dependency),
):
    """팀에 멤버 초대 (admin만 가능)"""
    try:
        return await invite_member(
            team_id, request.email, user, email_service
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(team_id: int, user_id: int, user=Depends(get_user)):
    """팀에서 멤버 제거 (admin만 가능)"""
    try:
        await remove_member(team_id, user_id, user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
