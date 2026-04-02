"""Ingest API integration tests.

Endpoints:
  POST /ingest/upload   — Upload file and start background ingest
  GET  /ingest/status    — Get document status for a team
  POST /ingest/check     — Check which files need uploading
"""
import io
from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember, UserRole
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from tests.conftest import auth_header


@pytest.fixture()
def app() -> FastAPI:
    """Test app with ingest router."""
    from maru_lang.api.endpoints.ingest import router
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture()
async def team_setup(user_alice: User):
    """Create a team with alice as editor role."""
    # Create editor role and assign to alice
    role = await UserRole.create(name="editor")
    user_alice.role_id = role.id
    await user_alice.save()

    team = await Team.create(name="IngestTeam", manager=user_alice, is_private=False)
    await TeamMember.create(user=user_alice, team=team, role="admin")
    return team, user_alice


# ──────────────────────────────────────────────
# 1. POST /ingest/upload
# ──────────────────────────────────────────────

class TestUpload:

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_upload_returns_document_id(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Upload returns document_id and status=uploading."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        resp = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "document_id" in data
        assert data["status"] == "uploading"
        assert data["name"] == "test"

    async def test_upload_requires_filename(
        self, client: AsyncClient, team_setup
    ):
        """Upload without file returns 400."""
        team, user = team_setup

        resp = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "0"},
        )
        # No file attached → 422 validation error
        assert resp.status_code == 422

    async def test_upload_unauthorized(self, client: AsyncClient):
        """Upload without auth returns 401."""
        resp = await client.post(
            "/ingest/upload",
            data={"team_id": "1", "mtime": "0"},
            files={"file": ("test.md", io.BytesIO(b"data"), "text/markdown")},
        )
        assert resp.status_code == 401


# ──────────────────────────────────────────────
# 2. GET /ingest/status
# ──────────────────────────────────────────────

class TestStatus:

    async def test_returns_documents_for_team(
        self, client: AsyncClient, team_setup
    ):
        """Status returns document list for the team."""
        team, user = team_setup

        # Create a document group and document
        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-001",
            name="test-doc",
            group=group,
            status=DocumentStatus.ACTIVE,
            file_size=100,
        )

        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == team.id
        assert data["total"] == 1
        assert data["documents"][0]["id"] == "doc-001"
        assert data["documents"][0]["status"] == "active"

    async def test_empty_team_returns_empty(
        self, client: AsyncClient, team_setup
    ):
        """Status for team with no documents returns empty list."""
        team, user = team_setup

        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["documents"] == []

    async def test_shows_error_status(
        self, client: AsyncClient, team_setup
    ):
        """Status shows error details for failed documents."""
        team, user = team_setup

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-err",
            name="broken",
            group=group,
            status=DocumentStatus.ERROR,
            error_message="Failed to parse PDF",
        )

        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=auth_header(user.id),
        )

        data = resp.json()
        doc = data["documents"][0]
        assert doc["status"] == "error"
        assert doc["error"] == "Failed to parse PDF"


# ──────────────────────────────────────────────
# 3. POST /ingest/check
# ──────────────────────────────────────────────

class TestCheck:

    async def test_new_files_need_upload(
        self, client: AsyncClient, team_setup
    ):
        """Check returns all indices when no documents exist."""
        _, user = team_setup

        resp = await client.post(
            "/ingest/check",
            headers=auth_header(user.id),
            json={
                "team_id": 1,
                "files": [
                    {"fileName": "a.md", "absolutePath": "/docs/a.md", "size": 100, "mtime": 1712000000.0},
                    {"fileName": "b.md", "absolutePath": "/docs/b.md", "size": 200, "mtime": 1712000000.0},
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["indices_to_upload"] == [0, 1]

    async def test_existing_file_skipped(
        self, client: AsyncClient, team_setup
    ):
        """Check skips files that already have matching fingerprint."""
        _, user = team_setup
        from maru_lang.utils.document import make_source_fingerprint_for_file

        # Pre-create a document with matching fingerprint
        fp = make_source_fingerprint_for_file("/docs/a.md", 100, int(1712000000.0 * 1e9))
        group = await DocumentGroup.create(name="uploads", team=(team_setup)[0])
        await Document.create(
            id="existing-doc",
            name="a",
            group=group,
            source_fingerprint=fp,
            status=DocumentStatus.ACTIVE,
        )

        resp = await client.post(
            "/ingest/check",
            headers=auth_header(user.id),
            json={
                "team_id": 1,
                "files": [
                    {"fileName": "a.md", "absolutePath": "/docs/a.md", "size": 100, "mtime": 1712000000.0},
                    {"fileName": "b.md", "absolutePath": "/docs/b.md", "size": 200, "mtime": 1712000000.0},
                ],
            },
        )

        data = resp.json()
        assert data["indices_to_upload"] == [1]  # only b.md needs upload
