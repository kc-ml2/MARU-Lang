"""Ingest API integration tests.

Endpoints:
  POST   /ingest/upload          — Upload file and start background ingest
  GET    /ingest/status          — Get document status for a team
  POST   /ingest/check           — Check which files need uploading
  DELETE /ingest/{document_id}   — Delete a document
"""
import io
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from fastapi import FastAPI

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember, UserRole
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup, DocumentAuditLog
from maru_lang.enums.documents import DocumentStatus, AuditAction
from tests.conftest import auth_header, user_bob


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
        """Upload returns document_id and status."""
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


# ──────────────────────────────────────────────
# 3.5 Upload group naming
# ──────────────────────────────────────────────

class TestUploadGroupNaming:

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_upload_creates_group_from_folder_path(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Upload with folder_path creates a group named after the folder."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        resp = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data={
                "team_id": str(team.id),
                "mtime": "1712000000.0",
                "folder_path": "/home/user/Documents/my-project",
            },
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )

        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]
        doc = await Document.get(id=doc_id)
        group = await DocumentGroup.get(id=doc.group_id)
        assert group.name == "my-project"

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_upload_without_folder_path_uses_uploads(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Upload without folder_path falls back to 'uploads' group."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        resp = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )

        assert resp.status_code == 200
        doc_id = resp.json()["document_id"]
        doc = await Document.get(id=doc_id)
        group = await DocumentGroup.get(id=doc.group_id)
        assert group.name == "uploads"


# ──────────────────────────────────────────────
# 4. POST /ingest/upload (duplicate / re-upload)
# ──────────────────────────────────────────────

class TestReupload:

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_reupload_same_file_returns_is_reupload(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Uploading the same file twice returns is_reupload=True without error."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        upload_data = {"team_id": str(team.id), "mtime": "1712000000.0"}
        file_payload = {"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")}

        # First upload
        resp1 = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data=upload_data,
            files=file_payload,
        )
        assert resp1.status_code == 200
        assert resp1.json()["is_reupload"] is False

        # Second upload (same fingerprint)
        file_payload2 = {"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")}
        resp2 = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data=upload_data,
            files=file_payload2,
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["is_reupload"] is True
        assert data2["document_id"] == resp1.json()["document_id"]

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_reupload_creates_audit_logs(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Re-upload creates both UPLOAD and RE_UPLOAD audit logs."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        upload_data = {"team_id": str(team.id), "mtime": "1712000000.0"}

        await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data=upload_data,
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )
        await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data=upload_data,
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )

        logs = await DocumentAuditLog.all()
        actions = [log.action for log in logs]
        assert AuditAction.UPLOAD in actions
        assert AuditAction.RE_UPLOAD in actions


# ──────────────────────────────────────────────
# 5. DELETE /ingest/{document_id}
# ──────────────────────────────────────────────

class TestDelete:

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_delete_document(
        self, mock_get_vdb, client: AsyncClient, team_setup
    ):
        """Delete removes document and creates audit log."""
        team, user = team_setup
        mock_vdb = MagicMock()
        mock_get_vdb.return_value = mock_vdb

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-del-001",
            name="to-delete",
            group=group,
            status=DocumentStatus.ACTIVE,
            file_size=100,
        )

        resp = await client.delete(
            f"/ingest/doc-del-001?team_id={team.id}",
            headers=auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["document_id"] == "doc-del-001"

        # Document should be gone
        assert await Document.get_or_none(id="doc-del-001") is None

        # VectorDB delete should have been called
        mock_vdb.delete_all_chunks_by_document_id.assert_called_once_with("doc-del-001")

        # Audit log should exist
        log = await DocumentAuditLog.filter(
            document_id="doc-del-001", action=AuditAction.DELETE,
        ).first()
        assert log is not None
        assert log.user_id == user.id

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, team_setup
    ):
        """Delete non-existent document returns 404."""
        team, user = team_setup

        resp = await client.delete(
            f"/ingest/nonexistent?team_id={team.id}",
            headers=auth_header(user.id),
        )
        assert resp.status_code == 404

    async def test_delete_unauthorized(self, client: AsyncClient):
        """Delete without auth returns 401."""
        resp = await client.delete("/ingest/doc-001?team_id=1")
        assert resp.status_code == 401

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_delete_non_admin_returns_403(
        self, mock_get_vdb, client: AsyncClient, team_setup, user_bob: User,
    ):
        """Non-admin team member cannot delete documents."""
        team, admin_user = team_setup

        # bob을 editor role로 설정하고 팀에 member로 추가
        role = await UserRole.get(name="editor")
        user_bob.role_id = role.id
        await user_bob.save()
        await TeamMember.create(user=user_bob, team=team, role="member")

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-no-perm",
            name="protected",
            group=group,
            status=DocumentStatus.ACTIVE,
        )

        resp = await client.delete(
            f"/ingest/doc-no-perm?team_id={team.id}",
            headers=auth_header(user_bob.id),
        )
        assert resp.status_code == 403


# ──────────────────────────────────────────────
# 6. GET /ingest/status (with audit logs)
# ──────────────────────────────────────────────

class TestStatusWithAudit:

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_status_includes_audit_logs(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup
    ):
        """Status response includes audit log entries per document."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        # Upload a file (creates UPLOAD audit log)
        resp = await client.post(
            "/ingest/upload",
            headers=auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )
        assert resp.status_code == 200

        # Check status
        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        doc = data["documents"][0]
        assert len(doc["audit_logs"]) >= 1
        assert doc["audit_logs"][0]["action"] == "upload"
        assert doc["audit_logs"][0]["user_name"] == "Alice"
