"""
Team management service
"""
import asyncio
from typing import Optional

from tortoise.exceptions import IntegrityError

from pathlib import Path
from maru_lang.core.relation_db.models.auth import Team, TeamMember, User
from maru_lang.core.relation_db.models.documents import (
    SourceStorage,
    TeamStorageLink,
)
from maru_lang.ports.email import EmailService
from maru_lang.settings import Settings
from maru_lang.enums import StorageOwnerType, TeamRole


async def _provision_team(root: Path, team: Team) -> None:
    """Ensure the team's independently owned default source storage exists."""
    from maru_lang.services.storage import ensure_default_source_storage

    await ensure_default_source_storage(root, team)


async def reconcile_team_storage(root: Path) -> int:
    """Idempotently bootstrap default storages for pre-existing teams."""
    teams = await Team.all()
    for team in teams:
        await _provision_team(root, team)
    return len(teams)


class TeamDeletionPendingError(Exception):
    """The team still owns a storage connected to another team."""


async def list_teams_by_user(user: User) -> list[dict]:
    """
    User가 속한 Team 목록을 역할 정보와 함께 조회
    """
    memberships = await TeamMember.filter(user=user).select_related("team")
    return [
        {
            "id": m.team.id,
            "name": m.team.name,
            "description": m.team.description,
            "role": m.role,
        }
        for m in memberships
    ]


async def get_team_detail(team_id: int, user: User) -> dict:
    """
    Team 상세 조회: 멤버와 접근 가능한 스토리지 수
    해당 팀의 멤버만 조회 가능
    """
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership:
        raise PermissionError("해당 팀의 멤버가 아닙니다")

    team = await Team.get(id=team_id)

    members_qs = await TeamMember.filter(team_id=team_id).select_related("user")
    members = [
        {
            "id": m.user.id,
            "email": m.user.email,
            "name": m.user.name,
            "role": m.role,
        }
        for m in members_qs
    ]

    storage_count = await TeamStorageLink.filter(team_id=team_id).count()

    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "members": members,
        "storage_count": storage_count,
    }


async def create_team(
    root: Path, name: str, creator: User, description: Optional[str] = None
) -> Team:
    """
    새 팀 생성. 생성자는 자동으로 admin.
    동일 이름 중복 방지.
    """
    if await Team.exists(name=name):
        raise ValueError(f"'{name}' 팀이 이미 존재합니다")

    team = await Team.create(
        name=name, description=description, manager=creator, is_personal=False
    )
    try:
        await _provision_team(root, team)
        await TeamMember.create(user=creator, team=team, role=TeamRole.ADMIN)
    except Exception:
        # Filesystem provisioning is part of team creation. Do not leave a DB
        # team that has no usable source space when it fails.
        await team.delete()
        raise
    return team


async def delete_team(
    root: Path, team_id: int, requester: User, *, delete_files: bool = False
) -> None:
    """Hard-delete a team, its document projections, and optional source files."""
    team = await Team.get_or_none(id=team_id)
    if team is None:
        raise LookupError("팀을 찾을 수 없습니다")
    await _check_admin(team_id, requester)
    if team.is_personal:
        raise PermissionError("개인 공간은 삭제할 수 없습니다")

    # An owned storage must outlive every team connected to it. Check this
    # before deleting any document so a rejected team deletion is non-destructive.
    owned_storages = await SourceStorage.filter(
        owner_type=StorageOwnerType.TEAM, owner_team_id=team_id
    ).all()
    for storage in owned_storages:
        shared = await TeamStorageLink.filter(storage_id=storage.id).exclude(
            team_id=team_id
        ).exists()
        if shared:
            raise TeamDeletionPendingError(
                "다른 팀에 연결된 스토리지를 먼저 연결 해제해주세요"
            )

    if delete_files:
        from maru_lang.utils.file_storage import remove_source_storage
        for storage in owned_storages:
            await asyncio.to_thread(remove_source_storage, root, storage.id)
    for storage in owned_storages:
        await storage.delete()
    await team.delete()


async def invite_member(
    team_id: int,
    email: str,
    inviter: User,
    *,
    settings: Settings,
    email_service: Optional[EmailService] = None,
) -> dict:
    """
    가입된 사용자를 이메일로 팀에 추가한다. admin만 가능하다.

    초대는 이메일만 받는다. 표시명(User.name)은 각 사용자가 본인 닉네임으로
    직접 설정하는 전역 값이므로, 초대가 기존 사용자의 이름을 덮어쓰지 않는다
    (덮어쓰면 그 사용자가 속한 다른 팀에서도 이름이 바뀌는 버그가 됨).
    """
    await _check_admin(team_id, inviter)

    if not settings.is_domain_allowed(email):
        raise ValueError("허용되지 않은 이메일 도메인입니다")

    team = await Team.get(id=team_id)
    target_user = await User.get_or_none(email=email)

    if target_user is None or not target_user.is_active:
        raise ValueError("가입한 사용자만 팀에 초대할 수 있습니다")

    member_role = TeamRole.MEMBER
    try:
        membership = await TeamMember.create(
            user=target_user, team_id=team_id, role=member_role
        )
    except IntegrityError:
        raise ValueError("이미 팀에 속한 멤버입니다")

    if email_service:
        inviter_name = inviter.name or inviter.email
        await email_service.send_notification(email, team.name, inviter_name)

    return {
        "id": target_user.id,
        "email": target_user.email,
        "name": target_user.name,
        "role": membership.role,
    }


async def remove_member(team_id: int, user_id: int, requester: User) -> None:
    """
    팀에서 멤버 제거. admin만 가능. 최소 1명의 admin 유지.
    """
    await _check_admin(team_id, requester)

    if requester.id == user_id:
        raise PermissionError("본인을 제거할 수 없습니다")

    membership = await TeamMember.get_or_none(team_id=team_id, user_id=user_id)
    if not membership:
        raise ValueError("해당 멤버를 찾을 수 없습니다")

    # admin 제거 시 최소 1명 유지 체크
    if membership.role == TeamRole.ADMIN:
        admin_count = await TeamMember.filter(
            team_id=team_id, role=TeamRole.ADMIN
        ).count()
        if admin_count <= 1:
            raise PermissionError("팀에 최소 1명의 admin이 필요합니다")

    await membership.delete()


async def _check_admin(team_id: int, user: User) -> TeamMember:
    """admin 권한 확인 헬퍼"""
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership or membership.role != TeamRole.ADMIN:
        raise PermissionError("admin 권한이 필요합니다")
    return membership


async def require_team_member(team_id: int, user: User) -> TeamMember:
    """Verify membership before a team-scoped operation."""
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership:
        raise PermissionError("해당 팀의 멤버가 아닙니다")
    return membership
