"""
Team management service
"""
from typing import Optional

from tortoise.exceptions import IntegrityError

from maru_lang.configs import get_config
from maru_lang.constants import ADMIN_EMAIL
from maru_lang.core.relation_db.models.auth import Team, TeamMember, User, UserRole
from maru_lang.core.relation_db.models.documents import DocumentGroup, Document
from maru_lang.dependencies.email import EmailService
from maru_lang.enums.auth import UserRoleCode
from maru_lang.services.llm import assign_balanced_llm

config = get_config()


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
    from maru_lang.graph.registry import registry_graph_ids, DEFAULT_GRAPH_IDS

    all_ids = registry_graph_ids()
    memberships = await TeamMember.filter(user=user).select_related("team")

    allowed: set[str] = set()
    for m in memberships:
        team_graphs = m.team.allowed_graphs or DEFAULT_GRAPH_IDS
        allowed |= set(team_graphs)

    return [gid for gid in all_ids if gid in allowed]


async def set_team_allowed_graphs(
    team_id: int, graph_ids: list[str], requester: User
) -> list[str]:
    """Set a team's allowed_graphs (admin only). Returns the saved list.

    Validates against the registry (unknown ids → ValueError) and stores the
    result in registry order. An empty list resets the team to the default set.
    """
    from maru_lang.graph.registry import registry_graph_ids

    await _check_admin(team_id, requester)

    all_ids = registry_graph_ids()
    unknown = [g for g in graph_ids if g not in all_ids]
    if unknown:
        raise ValueError(f"등록되지 않은 그래프: {', '.join(unknown)}")

    ordered = [gid for gid in all_ids if gid in set(graph_ids)]
    team = await Team.get(id=team_id)
    team.allowed_graphs = ordered
    await team.save()
    return ordered


def list_registerable_graphs() -> list[dict]:
    """Registered graphs as {id, description} for per-team configuration."""
    from maru_lang.graph.registry import registerable_graphs
    return registerable_graphs()


async def get_team_detail(team_id: int, user: User) -> dict:
    """
    Team 상세 조회: 멤버 목록 + 폴더(DocumentGroup) 목록
    해당 팀의 멤버만 조회 가능
    """
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership:
        raise PermissionError("해당 팀의 멤버가 아닙니다")

    team = await Team.get(id=team_id)

    # 멤버 목록 — 시스템 admin(CLI 부트스트랩 유저)은 사람이 아니므로 제외.
    # CLI가 닿는 모든 팀에 자동 가입되어, 빼지 않으면 모든 팀의 멤버 목록에 노출된다.
    members_qs = await TeamMember.filter(team_id=team_id).select_related("user")
    members = [
        {
            "id": m.user.id,
            "email": m.user.email,
            "name": m.user.name,
            "role": m.role,
        }
        for m in members_qs
        if m.user.email != ADMIN_EMAIL
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
        "description": team.description,
        "members": members,
        "folders": folders,
        "allowed_graphs": team.allowed_graphs or [],
    }


async def create_team(
    name: str, creator: User, description: Optional[str] = None
) -> Team:
    """
    새 팀 생성. 생성자는 자동으로 admin.
    동일 이름 중복 방지.
    """
    if await Team.exists(name=name):
        raise ValueError(f"'{name}' 팀이 이미 존재합니다")

    team = await Team.create(
        name=name, description=description, manager=creator, is_private=True
    )
    await TeamMember.create(user=creator, team=team, role="admin")
    return team


async def invite_member(
    team_id: int,
    email: str,
    inviter: User,
    email_service: Optional[EmailService] = None,
) -> dict:
    """
    이메일로 사용자를 팀에 초대. admin만 가능.
    - 미가입 유저: 익명 유저 생성 + invitation 이메일
    - 기존 유저: 팀 추가 + notification 이메일

    초대는 이메일만 받는다. 표시명(User.name)은 각 사용자가 본인 닉네임으로
    직접 설정하는 전역 값이므로, 초대가 기존 사용자의 이름을 덮어쓰지 않는다
    (덮어쓰면 그 사용자가 속한 다른 팀에서도 이름이 바뀌는 버그가 됨).
    """
    await _check_admin(team_id, inviter)

    if not config.auth.is_domain_allowed(email):
        raise ValueError("허용되지 않은 이메일 도메인입니다")

    team = await Team.get(id=team_id)
    target_user = await User.get_or_none(email=email)

    if target_user is None:
        # 익명 유저 생성 (초기 표시명은 이메일 local-part로 seed; 본인이 추후 변경)
        anonymous_role, _ = await UserRole.get_or_create(
            name=UserRoleCode.ANONYMOUS.value,
            defaults={"description": "초대로 생성된 미가입 유저"},
        )
        target_user = await User.create(
            email=email,
            name=email.split("@")[0],
            role=anonymous_role,
        )
        await assign_balanced_llm(target_user)
    # 기존 유저는 멤버십만 추가한다 (이름은 절대 건드리지 않음).

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


async def require_team_member(team_id: int, user: User) -> TeamMember:
    """현재 유저가 해당 팀의 멤버인지 확인. team-scoped 작업의 서버측 검증.

    클라이언트가 보낸 team_id를 그대로 신뢰하지 않기 위한 가드. delete처럼
    admin 권한까진 필요 없고 멤버 여부만 보면 되는 upload/status/check/retry에 쓴다.
    """
    membership = await TeamMember.get_or_none(team_id=team_id, user=user)
    if not membership:
        raise PermissionError("해당 팀의 멤버가 아닙니다")
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


async def get_or_create_domain_team(
    email: str,
    manager: User,
) -> tuple[Team, bool]:
    """이메일 도메인으로 조직(자동) 팀을 조회/생성한다.

    팀 이름은 도메인 첫 라벨(prefix)을 쓴다(예: alice@acme.com -> "acme").
    단, 같은 prefix 팀이 이미 있는데 그 팀의 실제 멤버(시스템 admin 제외)가
    "다른 전체 도메인"이면(예: 기존 acme.com 팀에 acme.co.kr 유입) 병합하지 않고
    전체 도메인 이름의 별도 팀으로 격리한다. 첫 라벨만 우연히 겹치는 무관한
    도메인이 한 조직 팀으로 섞이는 크로스 테넌트 멤버십을 막기 위함.

    manager: 자동 생성 팀의 소유자. 호출부에서 시스템 admin을 넘긴다(먼저 로그인한
    일반 유저가 조직 팀의 소유자가 되지 않도록).

    Returns:
        tuple[Team, bool]: (Team 인스턴스, 신규 생성 여부)
    """
    email_domain = email.split("@")[-1].lower()
    domain_prefix = email_domain.split(".")[0]

    team, created = await get_or_create_team(name=domain_prefix, manager=manager)
    if not created:
        # 기존 prefix 팀의 실제 멤버 도메인과 비교(시스템 admin은 role로 제외).
        members = (
            await TeamMember.filter(team=team)
            .exclude(role="admin")
            .prefetch_related("user")
        )
        member_domains = {
            m.user.email.split("@")[-1].lower() for m in members
        }
        if member_domains and email_domain not in member_domains:
            # 첫 라벨만 겹치는 다른 도메인 -> 전체 도메인 이름으로 격리(prefix 팀과 안 겹침).
            team, created = await get_or_create_team(
                name=email_domain, manager=manager
            )
    return team, created


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
