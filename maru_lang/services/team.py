"""
Team management service
"""
from typing import Optional

from tortoise.exceptions import IntegrityError

from maru_lang.configs import get_config
from maru_lang.core.relation_db.models.auth import Team, TeamMember, User, UserRole
from maru_lang.core.relation_db.models.documents import DocumentGroup, Document
from maru_lang.dependencies.email import EmailService
from maru_lang.enums.auth import UserRoleCode

config = get_config()


async def list_teams_by_user(user: User) -> list[dict]:
    """
    User가 속한 Team 목록을 역할 정보와 함께 조회
    """
    memberships = await TeamMember.filter(user=user).select_related("team")
    return [
        {"id": m.team.id, "name": m.team.name, "role": m.role}
        for m in memberships
    ]


def scope_team_ids(
    requested_team_ids,
    all_user_teams: list[dict],
) -> tuple[list[int], list[str]] | None:
    """Resolve a client's requested team_ids against the user's own teams.

    Used to scope chat document search per message. The request is never trusted:
    only teams the user actually belongs to survive.

    - unset/empty request -> all the user's teams
    - otherwise -> the intersection with the user's teams (order preserved)
    - returns None if the request names only teams the user can't access
      (the caller should reject the message)
    """
    if isinstance(requested_team_ids, int):
        requested_team_ids = [requested_team_ids]

    if requested_team_ids:
        requested = set(requested_team_ids)
        scoped = [t for t in all_user_teams if t["id"] in requested]
        if not scoped:
            return None
        return [t["id"] for t in scoped], [t["name"] for t in scoped]

    return [t["id"] for t in all_user_teams], [t["name"] for t in all_user_teams]


async def resolve_user_graph_ids(user: User) -> list[str]:
    """Graph ids the user may access = union over their teams' allowed_graphs.

    A team with an empty allowed_graphs grants only the default graph (not all),
    so newly registered graphs are opt-in per team. The result is intersected
    with the registry and returned in registry order.
    """
    # Imported lazily: the registry pulls in the graph stack (embeddings/transformers),
    # which we don't want to load just by importing this service module.
    from maru_lang.graph.registry import registry_graph_ids, DEFAULT_GRAPH_ID

    all_ids = registry_graph_ids()
    memberships = await TeamMember.filter(user=user).select_related("team")

    allowed: set[str] = set()
    for m in memberships:
        team_graphs = m.team.allowed_graphs or [DEFAULT_GRAPH_ID]
        allowed |= set(team_graphs)

    return [gid for gid in all_ids if gid in allowed]


async def get_team_detail(team_id: int, user: User) -> dict:
    """
    Team 상세 조회: 멤버 목록 + 폴더(DocumentGroup) 목록
    해당 팀의 멤버만 조회 가능
    """
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership:
        raise PermissionError("해당 팀의 멤버가 아닙니다")

    team = await Team.get(id=team_id)

    # 멤버 목록
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

    # 폴더(DocumentGroup) 목록 + 문서 수
    doc_groups = await DocumentGroup.filter(team_id=team_id).all()
    folders = []
    for dg in doc_groups:
        doc_count = await Document.filter(group_id=dg.id).count()
        folders.append({"id": dg.id, "name": dg.name, "document_count": doc_count})

    return {
        "id": team.id,
        "name": team.name,
        "members": members,
        "folders": folders,
    }


async def create_team(name: str, creator: User) -> Team:
    """
    새 팀 생성. 생성자는 자동으로 admin.
    동일 이름 중복 방지.
    """
    if await Team.exists(name=name):
        raise ValueError(f"'{name}' 팀이 이미 존재합니다")

    team = await Team.create(name=name, manager=creator, is_private=True)
    await TeamMember.create(user=creator, team=team, role="admin")
    return team


async def invite_member(
    team_id: int,
    email: str,
    name: str,
    inviter: User,
    email_service: Optional[EmailService] = None,
) -> dict:
    """
    이메일로 사용자를 팀에 초대. admin만 가능.
    - 미가입 유저: 익명 유저 생성 + invitation 이메일
    - 기존 유저: 팀 추가 + notification 이메일
    """
    await _check_admin(team_id, inviter)

    if not config.auth.is_domain_allowed(email):
        raise ValueError("허용되지 않은 이메일 도메인입니다")

    team = await Team.get(id=team_id)
    target_user = await User.get_or_none(email=email)

    if target_user is None:
        # 익명 유저 생성
        anonymous_role, _ = await UserRole.get_or_create(
            name=UserRoleCode.ANONYMOUS.value,
            defaults={"description": "초대로 생성된 미가입 유저"},
        )
        target_user = await User.create(
            email=email,
            name=name or email.split("@")[0],
            role=anonymous_role,
        )
    else:
        # 이름 업데이트 (초대 시 제공된 이름)
        if name and target_user.name != name:
            target_user.name = name
            await target_user.save()

    # 유저 롤이 anonymous면 아직 미가입 상태 → pending
    is_anonymous = await _is_anonymous_user(target_user)
    member_role = "pending" if is_anonymous else "member"
    try:
        membership = await TeamMember.create(
            user=target_user, team_id=team_id, role=member_role
        )
    except IntegrityError:
        raise ValueError("이미 팀에 속한 멤버입니다")

    # 이메일 전송: 미가입(anonymous) 유저면 invitation, 기존 유저면 notification
    if email_service:
        inviter_name = inviter.name or inviter.email
        if is_anonymous:
            email_service.send_invitation(email, team.name, inviter_name)
        else:
            email_service.send_notification(email, team.name, inviter_name)

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
    if membership.role == "admin":
        admin_count = await TeamMember.filter(
            team_id=team_id, role="admin"
        ).count()
        if admin_count <= 1:
            raise PermissionError("팀에 최소 1명의 admin이 필요합니다")

    await membership.delete()


async def _is_anonymous_user(user: User) -> bool:
    """유저가 anonymous 롤인지 확인"""
    if not user.role_id:
        return False
    role = await UserRole.get_or_none(id=user.role_id)
    return role is not None and role.name == UserRoleCode.ANONYMOUS.value


async def _check_admin(team_id: int, user: User) -> TeamMember:
    """admin 권한 확인 헬퍼"""
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership or membership.role != "admin":
        raise PermissionError("admin 권한이 필요합니다")
    return membership


async def get_or_create_team(
    name: str,
    manager: User,
    is_private: bool = False,
) -> tuple[Team, bool]:
    """
    Team을 조회하거나 생성

    Args:
        name: Team 이름
        manager: Team 관리자 User
        is_private: 비공개 여부

    Returns:
        tuple[Team, bool]: (Team 인스턴스, 신규 생성 여부)
    """
    team = await Team.get_or_none(name=name)
    if team:
        return team, False

    team = await Team.create(
        name=name,
        manager=manager,
        is_private=is_private,
    )
    return team, True


async def add_member_to_team(
    team: Team,
    user: User,
    role: str = "member",
) -> tuple[TeamMember, bool]:
    """
    User를 Team에 가입시킴

    Args:
        team: Team 인스턴스
        user: 가입시킬 User 인스턴스
        role: 역할 (기본값: "member")

    Returns:
        tuple[TeamMember, bool]: (TeamMember 인스턴스, 신규 생성 여부)
    """
    membership, created = await TeamMember.get_or_create(
        user=user,
        team=team,
        defaults={"role": role},
    )
    return membership, created
