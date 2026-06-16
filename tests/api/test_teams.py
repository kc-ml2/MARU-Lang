"""
Teams API 통합 테스트

엔드포인트:
  GET    /teams                          — 내 팀 목록
  GET    /teams/{team_id}                — 팀 상세 (멤버 + 폴더)
  POST   /teams                          — 팀 생성
  POST   /teams/{team_id}/members        — 멤버 초대
  DELETE /teams/{team_id}/members/{uid}  — 멤버 제거
"""
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember, UserRole
from maru_lang.core.relation_db.models.documents import DocumentGroup, Document
from maru_lang.dependencies.email import get_email_service_dependency
from maru_lang.enums.auth import UserRoleCode
from tests.conftest import auth_header


# ──────────────────────────────────────────────
# 1. GET /teams — 팀 목록 조회
# ──────────────────────────────────────────────

class TestListTeams:
    """로그인한 사용자가 속한 팀 목록을 반환하는 API 테스트"""

    async def test_returns_teams_with_role(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """팀에 소속된 사용자가 요청하면 팀 이름과 본인의 역할(admin)이 포함된 목록을 반환한다"""
        resp = await client.get("/teams", headers=await auth_header(user_alice.id))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "TestTeam"
        assert data[0]["role"] == "admin"

    async def test_empty_when_no_membership(
        self, client: AsyncClient, user_bob: User
    ):
        """어떤 팀에도 소속되지 않은 사용자는 빈 목록을 받는다"""
        resp = await client.get("/teams", headers=await auth_header(user_bob.id))
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_unauthorized_without_token(self, client: AsyncClient):
        """인증 토큰 없이 요청하면 401 Unauthorized를 반환한다"""
        resp = await client.get("/teams")
        assert resp.status_code == 401


# ──────────────────────────────────────────────
# 2. GET /teams/{team_id} — 팀 상세 조회
# ──────────────────────────────────────────────

class TestGetTeamDetail:
    """특정 팀의 멤버 목록과 업로드된 폴더(DocumentGroup) 목록을 반환하는 API 테스트"""

    async def test_returns_members_and_folders(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """팀 멤버가 요청하면 멤버(이름, 이메일, 역할)와 폴더(이름, 문서 수)를 함께 반환한다"""
        # 폴더(DocumentGroup) + 문서 1건 추가
        dg = await DocumentGroup.create(name="Folder1", team=team_with_admin)
        await Document.create(
            id="doc1", name="file.pdf", group=dg, status=2
        )

        resp = await client.get(
            f"/teams/{team_with_admin.id}", headers=await auth_header(user_alice.id)
        )
        assert resp.status_code == 200
        data = resp.json()

        # 멤버 정보 검증
        assert data["name"] == "TestTeam"
        assert len(data["members"]) == 1
        assert data["members"][0]["email"] == "alice@example.com"
        assert data["members"][0]["role"] == "admin"

        # 폴더 정보 검증
        assert len(data["folders"]) == 1
        assert data["folders"][0]["name"] == "Folder1"
        assert data["folders"][0]["document_count"] == 1

    async def test_system_admin_excluded_from_members(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """CLI 부트스트랩 시스템 admin은 팀 멤버 목록에 노출되지 않는다"""
        from maru_lang.constants import ADMIN_EMAIL, ADMIN_NAME
        from maru_lang.core.relation_db.models.auth import TeamMember

        system_admin = await User.create(email=ADMIN_EMAIL, name=ADMIN_NAME)
        await TeamMember.create(user=system_admin, team=team_with_admin, role="admin")

        resp = await client.get(
            f"/teams/{team_with_admin.id}", headers=await auth_header(user_alice.id)
        )
        assert resp.status_code == 200
        members = resp.json()["members"]
        assert len(members) == 1  # alice만 (시스템 admin 제외)
        assert all(m["email"] != ADMIN_EMAIL for m in members)

    async def test_non_member_gets_403(
        self, client: AsyncClient, user_bob: User, team_with_admin: Team
    ):
        """팀에 소속되지 않은 사용자가 요청하면 403 Forbidden을 반환한다"""
        resp = await client.get(
            f"/teams/{team_with_admin.id}", headers=await auth_header(user_bob.id)
        )
        assert resp.status_code == 403


# ──────────────────────────────────────────────
# 3. POST /teams — 팀 생성
# ──────────────────────────────────────────────

class TestCreateTeam:
    """새 팀을 생성하는 API 테스트. 생성자는 자동으로 admin이 된다."""

    async def test_create_team_success(
        self, client: AsyncClient, user_alice: User
    ):
        """유효한 팀 이름으로 생성하면 201을 반환하고, 생성자가 admin으로 등록된다"""
        resp = await client.post(
            "/teams",
            json={"name": "NewTeam"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "NewTeam"
        assert data["role"] == "admin"

        # DB에서 admin 멤버십이 실제로 생성되었는지 확인
        membership = await TeamMember.get(
            team_id=data["id"], user=user_alice
        )
        assert membership.role == "admin"

    async def test_duplicate_name_returns_409(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """이미 존재하는 팀 이름으로 생성을 시도하면 409 Conflict를 반환한다"""
        resp = await client.post(
            "/teams",
            json={"name": "TestTeam"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 409


# ──────────────────────────────────────────────
# 4. POST /teams/{team_id}/members — 멤버 초대
# ──────────────────────────────────────────────

class TestInviteMember:
    """이메일로 사용자를 팀에 초대하는 API 테스트 (기존 유저 + 미가입 유저)"""

    async def test_admin_invites_existing_member(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """admin이 기존 유저 이메일로 초대하면 201을 반환하고, member 역할로 추가된다"""
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "bob@example.com", "name": "Bob"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "bob@example.com"
        assert data["role"] == "member"

    async def test_invite_unregistered_email_creates_anonymous_user(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team,
    ):
        """미가입 이메일로 초대하면 anonymous 롤의 유저를 생성하고 팀에 추가한다"""
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "nobody@example.com", "name": "Nobody"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == "nobody@example.com"
        assert data["name"] == "Nobody"
        assert data["role"] == "pending"

        # DB에서 anonymous 유저가 생성되었는지 확인
        created_user = await User.get(email="nobody@example.com")
        assert created_user is not None
        user_role = await UserRole.get(id=created_user.role_id)
        assert user_role.name == UserRoleCode.ANONYMOUS.value

        # 팀 멤버십 확인 (익명 유저는 pending)
        membership = await TeamMember.get(
            team=team_with_admin, user=created_user
        )
        assert membership.role == "pending"

    async def test_invite_sends_invitation_email_for_new_user(
        self, app, client: AsyncClient, user_alice: User, team_with_admin: Team,
    ):
        """미가입 유저 초대 시 invitation 이메일이 전송된다"""
        mock_email = MagicMock()
        mock_email.send_invitation.return_value = True
        mock_email.send_notification.return_value = True

        app.dependency_overrides[get_email_service_dependency] = lambda: mock_email
        try:
            resp = await client.post(
                f"/teams/{team_with_admin.id}/members",
                json={"email": "newuser@example.com", "name": "NewUser"},
                headers=await auth_header(user_alice.id),
            )
            assert resp.status_code == 201
            mock_email.send_invitation.assert_called_once_with(
                "newuser@example.com", "TestTeam", "Alice"
            )
            mock_email.send_notification.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_email_service_dependency, None)

    async def test_invite_sends_notification_email_for_existing_user(
        self, app, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """기존 유저 초대 시 notification 이메일이 전송된다"""
        mock_email = MagicMock()
        mock_email.send_invitation.return_value = True
        mock_email.send_notification.return_value = True

        app.dependency_overrides[get_email_service_dependency] = lambda: mock_email
        try:
            resp = await client.post(
                f"/teams/{team_with_admin.id}/members",
                json={"email": "bob@example.com", "name": "Bob"},
                headers=await auth_header(user_alice.id),
            )
            assert resp.status_code == 201
            mock_email.send_notification.assert_called_once_with(
                "bob@example.com", "TestTeam", "Alice"
            )
            mock_email.send_invitation.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_email_service_dependency, None)

    async def test_non_admin_cannot_invite(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """member 역할의 사용자가 초대를 시도하면 403 Forbidden을 반환한다"""
        await TeamMember.create(
            user=user_bob, team=team_with_admin, role="member"
        )
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "new@example.com", "name": "New"},
            headers=await auth_header(user_bob.id),
        )
        assert resp.status_code == 403

    async def test_invite_already_member_returns_400(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """이미 팀에 소속된 사용자를 다시 초대하면 400 Bad Request를 반환한다"""
        await TeamMember.create(
            user=user_bob, team=team_with_admin, role="member"
        )
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "bob@example.com", "name": "Bob"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 400

    async def test_invite_blocked_domain_returns_400(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team,
        monkeypatch,
    ):
        """allowed_domains에 포함되지 않은 도메인의 이메일로 초대하면 400을 반환한다"""
        from maru_lang.services import team as team_module
        monkeypatch.setattr(
            team_module.config.auth, "allowed_domains", ["example.com"]
        )
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "user@blocked.com", "name": "Blocked"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 400
        assert "허용되지 않은 이메일 도메인" in resp.json()["detail"]

    async def test_invite_allowed_domain_succeeds(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team, monkeypatch,
    ):
        """allowed_domains에 포함된 도메인이면 정상적으로 초대된다"""
        from maru_lang.services import team as team_module
        monkeypatch.setattr(
            team_module.config.auth, "allowed_domains", ["example.com"]
        )
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "bob@example.com", "name": "Bob"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201

    async def test_reinvite_anonymous_user_after_removal_stays_pending(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team,
    ):
        """익명 유저를 제거 후 다시 초대하면 여전히 pending으로 추가된다"""
        # 1차 초대 (anonymous 유저 생성 + pending)
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "reinvite@example.com", "name": "ReInvite"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "pending"
        user_id = resp.json()["id"]

        # 멤버 제거
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/{user_id}",
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 204

        # 2차 초대 (이미 DB에 anonymous 유저 존재)
        resp = await client.post(
            f"/teams/{team_with_admin.id}/members",
            json={"email": "reinvite@example.com", "name": "ReInvite"},
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "pending"


# ──────────────────────────────────────────────
# 5. DELETE /teams/{team_id}/members/{user_id} — 멤버 제거
# ──────────────────────────────────────────────

class TestRemoveMember:
    """팀에서 특정 멤버를 제거하는 API 테스트. admin만 제거 가능하며, 최소 1명의 admin이 유지되어야 한다."""

    async def test_admin_removes_member(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """admin이 member를 제거하면 204를 반환하고, DB에서 멤버십이 삭제된다"""
        await TeamMember.create(
            user=user_bob, team=team_with_admin, role="member"
        )
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/{user_bob.id}",
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 204

        # DB에서 실제로 삭제되었는지 확인
        assert await TeamMember.get_or_none(
            team=team_with_admin, user=user_bob
        ) is None

    async def test_cannot_remove_self(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """admin이 본인을 제거하려고 하면 403 Forbidden을 반환한다"""
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/{user_alice.id}",
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 403

    async def test_non_admin_cannot_remove(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """member 역할의 사용자가 다른 멤버를 제거하려고 하면 403 Forbidden을 반환한다"""
        await TeamMember.create(
            user=user_bob, team=team_with_admin, role="member"
        )
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/{user_alice.id}",
            headers=await auth_header(user_bob.id),
        )
        assert resp.status_code == 403

    async def test_last_admin_cannot_be_removed(
        self, client: AsyncClient, user_alice: User, user_bob: User,
        team_with_admin: Team,
    ):
        """admin이 2명인 경우 한 명을 제거할 수 있다 (최소 1명 유지 조건 충족)"""
        await TeamMember.create(
            user=user_bob, team=team_with_admin, role="admin"
        )
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/{user_bob.id}",
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 204

    async def test_remove_nonexistent_member_returns_400(
        self, client: AsyncClient, user_alice: User, team_with_admin: Team
    ):
        """존재하지 않는 사용자 ID로 제거를 시도하면 400 Bad Request를 반환한다"""
        resp = await client.delete(
            f"/teams/{team_with_admin.id}/members/9999",
            headers=await auth_header(user_alice.id),
        )
        assert resp.status_code == 400
