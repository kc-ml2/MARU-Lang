"""Team-membership guard on the ingest endpoints.

team_id is client-supplied, so every team-scoped endpoint must reject a
non-member server-side (even one with the editor role) — not just delete.
"""
import io

import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember, UserRole
from tests.conftest import auth_header


@pytest.fixture()
def app() -> FastAPI:
    from maru_lang.api.endpoints.ingest import router
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture()
async def team_setup(user_alice: User):
    """A team with alice as an admin member, plus the editor role."""
    role = await UserRole.create(name="editor")
    user_alice.role_id = role.id
    await user_alice.save()

    team = await Team.create(name="IngestTeam", manager=user_alice, is_private=False)
    await TeamMember.create(user=user_alice, team=team, role="admin")
    return team, user_alice


@pytest.fixture()
async def non_member_editor(team_setup, user_bob: User) -> User:
    """An editor-role user who is NOT a member of team_setup's team."""
    role = await UserRole.get(name="editor")
    user_bob.role_id = role.id
    await user_bob.save()
    return user_bob


class TestTeamMembership:

    async def test_upload_non_member_returns_403(
        self, client: AsyncClient, team_setup, non_member_editor
    ):
        team, _ = team_setup
        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(non_member_editor.id),
            data={"team_id": str(team.id), "mtime": "0"},
            files={"file": ("x.md", io.BytesIO(b"# hi"), "text/markdown")},
        )
        assert resp.status_code == 403

    async def test_status_non_member_returns_403(
        self, client: AsyncClient, team_setup, non_member_editor
    ):
        team, _ = team_setup
        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=await auth_header(non_member_editor.id),
        )
        assert resp.status_code == 403

    async def test_check_non_member_returns_403(
        self, client: AsyncClient, team_setup, non_member_editor
    ):
        team, _ = team_setup
        resp = await client.post(
            "/ingest/check",
            headers=await auth_header(non_member_editor.id),
            json={"team_id": team.id, "files": []},
        )
        assert resp.status_code == 403

    async def test_retry_non_member_returns_403(
        self, client: AsyncClient, team_setup, non_member_editor
    ):
        team, _ = team_setup
        resp = await client.post(
            f"/ingest/doc-xyz/retry?team_id={team.id}",
            headers=await auth_header(non_member_editor.id),
        )
        # Membership is checked before document lookup, so this is 403 (not 404).
        assert resp.status_code == 403
