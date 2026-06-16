"""Ingest API integration tests.

Endpoints:
  POST   /ingest/upload          — Upload file and start background ingest
  GET    /ingest/status          — Get document status for a team
  POST   /ingest/check           — Check which files need uploading
  DELETE /ingest/{document_id}   — Delete a document
"""
import io
import os
import time
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
            headers=await auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "document_id" in data
        assert data["name"] == "test"
        # No task queue -> in-process synchronous ingest; response reflects the
        # real outcome ("active") and run_ingest_for_document was awaited.
        assert data["status"] == "active"
        mock_ingest.assert_awaited_once()

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_upload_enqueues_when_task_queue_enabled(
        self, mock_save, mock_ingest, app: FastAPI, client: AsyncClient, team_setup
    ):
        """With app.state.arq present, upload enqueues to the worker instead of
        running ingest in-process."""
        from maru_lang.constants import INGEST_TASK_NAME

        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/path.md"

        fake_arq = MagicMock()
        fake_arq.enqueue_job = AsyncMock()
        app.state.arq = fake_arq

        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("queued.md", io.BytesIO(b"# Hi"), "text/markdown")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        # Enqueued under the shared constant name, not run in-process.
        fake_arq.enqueue_job.assert_awaited_once()
        assert fake_arq.enqueue_job.await_args.args[0] == INGEST_TASK_NAME
        assert fake_arq.enqueue_job.await_args.args[1] == data["document_id"]
        mock_ingest.assert_not_called()

    async def test_upload_requires_filename(
        self, client: AsyncClient, team_setup
    ):
        """Upload without file returns 400."""
        team, user = team_setup

        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["team_id"] == team.id
        assert data["total"] == 1
        assert data["documents"][0]["id"] == "doc-001"
        assert data["documents"][0]["status"] == "active"

    async def test_status_filters_by_group_id(
        self, client: AsyncClient, team_setup
    ):
        """group_id scopes the listing to one folder; cross-team group yields empty."""
        team, user = team_setup
        g1 = await DocumentGroup.create(name="folder-a", team=team)
        g2 = await DocumentGroup.create(name="folder-b", team=team)
        await Document.create(id="doc-a", name="a", group=g1,
                              status=DocumentStatus.ACTIVE, file_size=1)
        await Document.create(id="doc-b", name="b", group=g2,
                              status=DocumentStatus.ACTIVE, file_size=1)

        resp = await client.get(
            f"/ingest/status?team_id={team.id}&group_id={g1.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["documents"][0]["id"] == "doc-a"
        assert data["documents"][0]["group_id"] == g1.id

        # Unknown/foreign group id → empty (team filter intersects), not a leak.
        resp = await client.get(
            f"/ingest/status?team_id={team.id}&group_id=999999",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_check_does_not_skip_failed_documents(
        self, client: AsyncClient, team_setup
    ):
        """ERROR 문서는 fingerprint가 같아도 재업로드 대상 (issue #15)."""
        from maru_lang.services.ingest import _upload_fingerprint
        team, user = team_setup
        fp = _upload_fingerprint(team.id, "/docs/fail.md", 100, 1712000000.0)
        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="failed-doc", name="fail", group=group,
            source_fingerprint=fp, status=DocumentStatus.ERROR, error_message="boom",
        )

        resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={"team_id": team.id, "files": [
                {"fileName": "fail.md", "absolutePath": "/docs/fail.md",
                 "size": 100, "mtime": 1712000000.0},
            ]},
        )
        assert resp.json()["indices_to_upload"] == [0]  # 스킵되지 않음

    async def test_empty_team_returns_empty(
        self, client: AsyncClient, team_setup
    ):
        """Status for team with no documents returns empty list."""
        team, user = team_setup

        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
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
        team, user = team_setup
        from maru_lang.services.ingest import _upload_fingerprint

        # Pre-create a document with matching (team-scoped) fingerprint
        fp = _upload_fingerprint(team.id, "/docs/a.md", 100, 1712000000.0)
        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="existing-doc",
            name="a",
            group=group,
            source_fingerprint=fp,
            status=DocumentStatus.ACTIVE,
        )

        resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
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
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
            data=upload_data,
            files=file_payload,
        )
        assert resp1.status_code == 200
        assert resp1.json()["is_reupload"] is False

        # Second upload (same fingerprint)
        file_payload2 = {"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")}
        resp2 = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
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
            headers=await auth_header(user.id),
            data=upload_data,
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )
        await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
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

class TestRetry:

    @staticmethod
    async def _make_doc(team, status, doc_id="doc-retry-001"):
        group = await DocumentGroup.create(name="uploads", team=team)
        return await Document.create(
            id=doc_id, name="retryme", group=group,
            status=status, file_size=100, error_message="boom" if status == DocumentStatus.ERROR else None,
        )

    async def test_retry_error_doc_enqueues(self, app, client: AsyncClient, team_setup):
        """ERROR doc + queue on → reset to UPLOADING and enqueued."""
        from maru_lang.constants import INGEST_TASK_NAME
        team, user = team_setup
        await self._make_doc(team, DocumentStatus.ERROR)

        fake_arq = MagicMock()
        fake_arq.enqueue_job = AsyncMock()
        app.state.arq = fake_arq

        resp = await client.post(
            f"/ingest/doc-retry-001/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        fake_arq.enqueue_job.assert_awaited_once_with(INGEST_TASK_NAME, "doc-retry-001", team.id)

        doc = await Document.get(id="doc-retry-001")
        assert doc.status == DocumentStatus.UPLOADING
        assert doc.error_message is None

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    async def test_retry_error_doc_in_process_is_synchronous(
        self, mock_ingest, client: AsyncClient, team_setup
    ):
        """Queue off → runs synchronously and reports the real outcome."""
        team, user = team_setup
        await self._make_doc(team, DocumentStatus.ERROR)

        resp = await client.post(
            f"/ingest/doc-retry-001/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "active"
        mock_ingest.assert_awaited_once()

    async def test_retry_active_requires_force(self, client: AsyncClient, team_setup):
        """ACTIVE doc: 409 without force, allowed with force."""
        team, user = team_setup
        await self._make_doc(team, DocumentStatus.ACTIVE)

        resp = await client.post(
            f"/ingest/doc-retry-001/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 409

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    async def test_retry_active_with_force(self, mock_ingest, client: AsyncClient, team_setup):
        team, user = team_setup
        await self._make_doc(team, DocumentStatus.ACTIVE)

        resp = await client.post(
            f"/ingest/doc-retry-001/retry?team_id={team.id}&force=true",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 200
        mock_ingest.assert_awaited_once()

    async def test_retry_never_touches_in_flight(self, client: AsyncClient, team_setup):
        """PROCESSING/DELETING are never retryable, even with force."""
        team, user = team_setup
        await self._make_doc(team, DocumentStatus.PROCESSING)

        resp = await client.post(
            f"/ingest/doc-retry-001/retry?team_id={team.id}&force=true",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 409
        doc = await Document.get(id="doc-retry-001")
        assert doc.status == DocumentStatus.PROCESSING  # untouched

    async def test_retry_unknown_doc_404(self, client: AsyncClient, team_setup):
        team, user = team_setup
        resp = await client.post(
            f"/ingest/nope/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 404


class TestStateTransitions:
    async def test_begin_processing_reclaims_error_doc(self, team_setup):
        """ARQ 잡 재시도가 ERROR 문서를 재처리할 수 있어야 한다
        (이전엔 claim 실패 → cancelled로 오인 → 문서가 삭제되는 버그)."""
        from maru_lang.services.document import begin_processing
        team, _ = team_setup
        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(id="err-doc", name="e", group=group,
                              status=DocumentStatus.ERROR, file_size=1)

        assert await begin_processing("err-doc") is True
        assert (await Document.get(id="err-doc")).status == DocumentStatus.PROCESSING

    async def test_begin_processing_rejects_terminal_and_deleting(self, team_setup):
        from maru_lang.services.document import begin_processing
        team, _ = team_setup
        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(id="act-doc", name="a", group=group,
                              status=DocumentStatus.ACTIVE, file_size=1)
        await Document.create(id="del-doc", name="d", group=group,
                              status=DocumentStatus.DELETING, file_size=1)

        assert await begin_processing("act-doc") is False
        assert await begin_processing("del-doc") is False


class TestGroupRetry:

    @staticmethod
    async def _folder_with_mixed_docs(team):
        group = await DocumentGroup.create(name="folder", team=team)
        await Document.create(id="g-err", name="err", group=group,
                              status=DocumentStatus.ERROR, file_size=1, error_message="boom")
        await Document.create(id="g-act", name="act", group=group,
                              status=DocumentStatus.ACTIVE, file_size=1)
        await Document.create(id="g-proc", name="proc", group=group,
                              status=DocumentStatus.PROCESSING, file_size=1)
        return group

    async def test_group_retry_enqueues_error_docs_only(self, app, client: AsyncClient, team_setup):
        from maru_lang.constants import INGEST_TASK_NAME
        team, user = team_setup
        group = await self._folder_with_mixed_docs(team)

        fake_arq = MagicMock()
        fake_arq.enqueue_job = AsyncMock()
        app.state.arq = fake_arq

        resp = await client.post(
            f"/ingest/groups/{group.id}/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["skipped"] == 2  # active (no force) + processing
        assert data["requeued"][0]["document_id"] == "g-err"
        fake_arq.enqueue_job.assert_awaited_once_with(INGEST_TASK_NAME, "g-err", team.id)

        assert (await Document.get(id="g-err")).status == DocumentStatus.UPLOADING
        assert (await Document.get(id="g-act")).status == DocumentStatus.ACTIVE
        assert (await Document.get(id="g-proc")).status == DocumentStatus.PROCESSING

    async def test_group_retry_force_includes_active(self, app, client: AsyncClient, team_setup):
        team, user = team_setup
        group = await self._folder_with_mixed_docs(team)

        fake_arq = MagicMock()
        fake_arq.enqueue_job = AsyncMock()
        app.state.arq = fake_arq

        resp = await client.post(
            f"/ingest/groups/{group.id}/retry?team_id={team.id}&force=true",
            headers=await auth_header(user.id),
        )
        data = resp.json()
        assert data["count"] == 2          # error + active
        assert data["skipped"] == 1        # processing never retried
        assert fake_arq.enqueue_job.await_count == 2

    async def test_group_retry_requires_queue(self, client: AsyncClient, team_setup):
        """Queue off → 409, and no document status is touched."""
        team, user = team_setup
        group = await self._folder_with_mixed_docs(team)

        resp = await client.post(
            f"/ingest/groups/{group.id}/retry?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 409
        assert (await Document.get(id="g-err")).status == DocumentStatus.ERROR


class TestGroupDelete:

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_deletes_subtree_including_child_folder_docs(
        self, mock_get_vdb, client: AsyncClient, team_setup
    ):
        """폴더 삭제는 하위 폴더의 문서까지 전체 트리를 정리한다."""
        team, user = team_setup
        mock_get_vdb.return_value = MagicMock()

        parent = await DocumentGroup.create(name="parent", team=team)
        child = await DocumentGroup.create(name="child", team=team, parent=parent)
        await Document.create(id="p-doc", name="p", group=parent,
                              status=DocumentStatus.ACTIVE, file_size=1)
        await Document.create(id="c-doc", name="c", group=child,
                              status=DocumentStatus.ACTIVE, file_size=1)

        resp = await client.delete(
            f"/ingest/groups/{parent.id}?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == 2          # 부모+자식 폴더 문서 모두
        assert data["deferred"] == 0
        assert data["group_removed"] is True

        assert await Document.get_or_none(id="p-doc") is None
        assert await Document.get_or_none(id="c-doc") is None
        assert await DocumentGroup.get_or_none(id=parent.id) is None  # 폴더 트리 제거
        assert await DocumentGroup.get_or_none(id=child.id) is None

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_in_flight_doc_defers_and_keeps_folder(
        self, mock_get_vdb, client: AsyncClient, team_setup
    ):
        """처리중 문서는 DELETING으로 지연되고, 폴더 행은 워커 정리 전까지 유지."""
        team, user = team_setup
        mock_get_vdb.return_value = MagicMock()

        group = await DocumentGroup.create(name="busy", team=team)
        await Document.create(id="busy-doc", name="b", group=group,
                              status=DocumentStatus.PROCESSING, file_size=1)

        resp = await client.delete(
            f"/ingest/groups/{group.id}?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        data = resp.json()
        assert data["deferred"] == 1 and data["deleted"] == 0
        assert data["group_removed"] is False

        doc = await Document.get(id="busy-doc")
        assert doc.status == DocumentStatus.DELETING        # 워커가 마무리
        assert await DocumentGroup.get_or_none(id=group.id) is not None

    async def test_unknown_or_foreign_group_404(self, client: AsyncClient, team_setup):
        team, user = team_setup
        resp = await client.delete(
            f"/ingest/groups/999999?team_id={team.id}",
            headers=await auth_header(user.id),
        )
        assert resp.status_code == 404


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
            headers=await auth_header(user.id),
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

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_delete_in_flight_defers_to_worker(
        self, mock_get_vdb, client: AsyncClient, team_setup
    ):
        """Deleting a PROCESSING doc marks it DELETING (no hard-delete/chunk race)."""
        team, user = team_setup
        mock_vdb = MagicMock()
        mock_get_vdb.return_value = mock_vdb

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-inflight", name="processing", group=group,
            status=DocumentStatus.PROCESSING, file_size=100,
        )

        resp = await client.delete(
            f"/ingest/doc-inflight?team_id={team.id}", headers=await auth_header(user.id),
        )
        assert resp.status_code == 200

        # Deferred: row kept (now DELETING), chunks NOT touched (worker owns them).
        doc = await Document.get_or_none(id="doc-inflight")
        assert doc is not None
        assert doc.status == DocumentStatus.DELETING
        mock_vdb.delete_all_chunks_by_document_id.assert_not_called()
        # Intent still audited.
        assert await DocumentAuditLog.filter(
            document_id="doc-inflight", action=AuditAction.DELETE,
        ).exists()

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_reconcile_finalizes_deleting(
        self, mock_get_vdb, team_setup
    ):
        """reconcile_deletions() finalizes docs stuck in DELETING."""
        from maru_lang.services.ingest import reconcile_deletions
        team, _ = team_setup
        mock_vdb = MagicMock()
        mock_get_vdb.return_value = mock_vdb

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-deleting", name="stuck", group=group,
            status=DocumentStatus.DELETING, file_size=100,
        )

        n = await reconcile_deletions()
        assert n >= 1
        assert await Document.get_or_none(id="doc-deleting") is None
        mock_vdb.delete_all_chunks_by_document_id.assert_any_call("doc-deleting")

    @patch("maru_lang.services.ingest.get_vector_db")
    async def test_delete_removes_storage_dir(
        self, mock_get_vdb, client: AsyncClient, team_setup, tmp_path
    ):
        """삭제 시 storage 디렉터리(…/<doc_id>/)도 정리된다 (issue #8)."""
        team, user = team_setup
        mock_get_vdb.return_value = MagicMock()

        doc_dir = tmp_path / "doc-st-001"
        doc_dir.mkdir()
        stored = doc_dir / "original.md"
        stored.write_text("content")

        group = await DocumentGroup.create(name="uploads", team=team)
        await Document.create(
            id="doc-st-001", name="stored", group=group,
            status=DocumentStatus.ACTIVE, file_size=7, storage_path=str(stored),
        )

        resp = await client.delete(
            f"/ingest/doc-st-001?team_id={team.id}", headers=await auth_header(user.id),
        )
        assert resp.status_code == 200
        assert not doc_dir.exists()  # 파일 + 디렉터리 제거됨

    async def test_delete_nonexistent_returns_404(
        self, client: AsyncClient, team_setup
    ):
        """Delete non-existent document returns 404."""
        team, user = team_setup

        resp = await client.delete(
            f"/ingest/nonexistent?team_id={team.id}",
            headers=await auth_header(user.id),
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
            headers=await auth_header(user_bob.id),
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
            headers=await auth_header(user.id),
            data={"team_id": str(team.id), "mtime": "1712000000.0"},
            files={"file": ("test.md", io.BytesIO(b"# Hello"), "text/markdown")},
        )
        assert resp.status_code == 200

        # Check status
        resp = await client.get(
            f"/ingest/status?team_id={team.id}",
            headers=await auth_header(user.id),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        doc = data["documents"][0]
        assert len(doc["audit_logs"]) >= 1
        assert doc["audit_logs"][0]["action"] == "upload"
        assert doc["audit_logs"][0]["user_name"] == "Alice"


# ──────────────────────────────────────────────
# 7. Check → Upload → Check 전체 플로우 (실제 파일 기반)
# ──────────────────────────────────────────────

class TestCheckUploadFlow:
    """클라이언트의 실제 사용 패턴을 시뮬레이션하는 테스트.

    클라이언트 플로우: check → upload → check (재확인)
    실제 파일을 생성하여 size/mtime 값이 현실적인 조건에서 동작을 검증.
    """

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_check_upload_check_skips_uploaded_file(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """check → upload → check: 업로드한 파일은 두 번째 check에서 스킵되어야 한다."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/test.md"

        # 실제 파일 생성
        test_file = tmp_path / "test.md"
        test_file.write_text("# 테스트 문서\n\n이것은 테스트입니다.")
        stat = test_file.stat()
        abs_path = str(test_file)
        file_size = stat.st_size
        file_mtime = stat.st_mtime

        # 1단계: check — 새 파일이므로 업로드 필요
        check_resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": "test.md", "absolutePath": abs_path,
                     "size": file_size, "mtime": file_mtime},
                ],
            },
        )
        assert check_resp.status_code == 200
        assert check_resp.json()["indices_to_upload"] == [0]

        # 2단계: upload — check에서 사용한 것과 동일한 경로 정보로 업로드
        folder_path = str(tmp_path)
        with open(test_file, "rb") as f:
            content = f.read()

        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
            data={
                "team_id": str(team.id),
                "mtime": str(file_mtime),
                "folder_path": folder_path,
            },
            files={"file": ("test.md", io.BytesIO(content), "text/markdown")},
        )
        assert resp.status_code == 200
        assert resp.json()["is_reupload"] is False

        # 3단계: check 재호출 — 이미 업로드했으므로 스킵되어야 함
        check_resp2 = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": "test.md", "absolutePath": abs_path,
                     "size": file_size, "mtime": file_mtime},
                ],
            },
        )
        assert check_resp2.status_code == 200
        assert check_resp2.json()["indices_to_upload"] == [], \
            "업로드된 파일은 check에서 스킵되어야 하지만, 다시 업로드 대상으로 반환됨"

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_check_detects_modified_file_after_upload(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """업로드 후 파일을 수정하면 check에서 다시 업로드 대상으로 반환해야 한다."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/doc.txt"

        # 파일 생성 및 업로드
        test_file = tmp_path / "doc.txt"
        test_file.write_text("원본 내용")
        stat = test_file.stat()
        abs_path = str(test_file)
        folder_path = str(tmp_path)

        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
            data={
                "team_id": str(team.id),
                "mtime": str(stat.st_mtime),
                "folder_path": folder_path,
            },
            files={"file": ("doc.txt", io.BytesIO(test_file.read_bytes()), "text/plain")},
        )
        assert resp.status_code == 200

        # 파일 수정 (내용/크기/mtime 변경)
        time.sleep(0.05)  # mtime 차이 보장
        test_file.write_text("수정된 내용 — 더 긴 텍스트를 추가합니다.")
        new_stat = test_file.stat()

        # check — 수정된 파일은 다시 업로드 대상
        check_resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": "doc.txt", "absolutePath": abs_path,
                     "size": new_stat.st_size, "mtime": new_stat.st_mtime},
                ],
            },
        )
        assert check_resp.status_code == 200
        assert check_resp.json()["indices_to_upload"] == [0], \
            "수정된 파일은 check에서 업로드 대상으로 반환되어야 함"

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_fingerprint_mismatch_when_paths_differ(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """check의 absolutePath와 upload의 folder_path/filename이 다르면 fingerprint 불일치.

        이 테스트는 클라이언트가 check과 upload에서 다른 경로를 보내는 경우를 재현한다.
        예: check에서는 절대경로를, upload에서는 상대 folder_path를 보내는 경우.
        """
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/report.md"

        test_file = tmp_path / "report.md"
        test_file.write_text("# 보고서\n\n내용입니다.")
        stat = test_file.stat()
        abs_path = str(test_file)  # e.g. /tmp/pytest-xxx/report.md

        # upload: 상대 folder_path 사용 (클라이언트가 다른 값을 보낸 경우)
        relative_folder = "my-project"
        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
            data={
                "team_id": str(team.id),
                "mtime": str(stat.st_mtime),
                "folder_path": relative_folder,
            },
            files={"file": ("report.md", io.BytesIO(test_file.read_bytes()), "text/markdown")},
        )
        assert resp.status_code == 200

        # check: 절대경로 사용 (원래 파일 위치)
        check_resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": "report.md", "absolutePath": abs_path,
                     "size": stat.st_size, "mtime": stat.st_mtime},
                ],
            },
        )
        data = check_resp.json()
        # fingerprint 불일치 → check은 "업로드 필요"로 판단 (스킵되지 않음)
        assert data["indices_to_upload"] == [0], \
            "경로가 다르면 fingerprint가 불일치하여 스킵되지 않아야 함 — 이것이 '항상 스킵 안 됨' 버그의 원인"

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_multiple_files_partial_skip(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """여러 파일 중 일부만 업로드된 경우, check은 미업로드 파일만 반환해야 한다."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/file.md"

        # 파일 3개 생성
        files_info = []
        for name in ["a.md", "b.md", "c.md"]:
            f = tmp_path / name
            f.write_text(f"# {name}\n\n내용")
            stat = f.stat()
            files_info.append({
                "path": str(f),
                "name": name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "content": f.read_bytes(),
            })

        folder_path = str(tmp_path)

        # a.md만 업로드
        resp = await client.post(
            "/ingest/upload",
            headers=await auth_header(user.id),
            data={
                "team_id": str(team.id),
                "mtime": str(files_info[0]["mtime"]),
                "folder_path": folder_path,
            },
            files={"file": ("a.md", io.BytesIO(files_info[0]["content"]), "text/markdown")},
        )
        assert resp.status_code == 200

        # check 3개 파일 — a.md는 스킵, b.md/c.md는 업로드 필요
        check_resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": fi["name"], "absolutePath": fi["path"],
                     "size": fi["size"], "mtime": fi["mtime"]}
                    for fi in files_info
                ],
            },
        )
        data = check_resp.json()
        assert data["indices_to_upload"] == [1, 2], \
            "a.md는 스킵되고 b.md, c.md만 업로드 대상이어야 함"

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_modified_reupload_updates_same_document(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """문서 A를 수정해 다시 올리면 새 문서가 생기는 게 아니라 A가 갱신되어야 한다.

        (기존 버그: fingerprint(size/mtime 포함)를 정체성으로 써서, 수정된 파일은
        fingerprint가 달라져 새 문서가 추가되고 옛 문서가 그대로 남았다.)
        """
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/doc.md"

        f = tmp_path / "doc.md"
        f.write_text("v1")
        folder_path = str(tmp_path)

        resp1 = await client.post(
            "/ingest/upload", headers=await auth_header(user.id),
            data={"team_id": str(team.id), "mtime": str(f.stat().st_mtime),
                  "folder_path": folder_path},
            files={"file": ("doc.md", io.BytesIO(b"v1"), "text/markdown")},
        )
        doc_id_1 = resp1.json()["document_id"]
        fp_v1 = (await Document.get(id=doc_id_1)).source_fingerprint

        # 수정: 내용/크기/mtime이 달라진 같은 파일
        f.write_text("v2 — modified, longer content")
        resp2 = await client.post(
            "/ingest/upload", headers=await auth_header(user.id),
            data={"team_id": str(team.id), "mtime": str(f.stat().st_mtime + 10),
                  "folder_path": folder_path},
            files={"file": ("doc.md", io.BytesIO(b"v2 modified, longer content"), "text/markdown")},
        )

        data2 = resp2.json()
        assert data2["is_reupload"] is True
        assert data2["document_id"] == doc_id_1  # 같은 문서 갱신, 새 문서 없음

        docs = await Document.filter(group__team_id=team.id).all()
        assert len(docs) == 1  # 옛 문서가 남지 않음
        assert docs[0].source_fingerprint != fp_v1  # 변경 표식 갱신됨
        assert docs[0].status == DocumentStatus.UPLOADING  # 재처리 대기

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_same_file_different_team_is_separate_document(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, user_bob, tmp_path,
    ):
        """다른 팀이 같은 파일(이름/크기/mtime)을 올려도 남의 팀 문서를 덮지 않는다."""
        from maru_lang.core.relation_db.models.auth import Team, TeamMember, UserRole
        team, user = team_setup
        editor = await UserRole.get_or_none(name="editor")  # team_setup이 생성
        user_bob.role_id = editor.id
        await user_bob.save()
        team_b = await Team.create(name="team-b", manager=user_bob, is_private=False)
        await TeamMember.create(user=user_bob, team=team_b, role="admin")
        mock_save.return_value = "/tmp/fake/storage/shared.md"

        common = {"mtime": "1712000000.0", "folder_path": "/shared"}
        r1 = await client.post(
            "/ingest/upload", headers=await auth_header(user.id),
            data={"team_id": str(team.id), **common},
            files={"file": ("shared.md", io.BytesIO(b"same"), "text/markdown")},
        )
        r2 = await client.post(
            "/ingest/upload", headers=await auth_header(user_bob.id),
            data={"team_id": str(team_b.id), **common},
            files={"file": ("shared.md", io.BytesIO(b"same"), "text/markdown")},
        )

        assert r1.status_code == 200 and r2.status_code == 200
        assert r2.json()["is_reupload"] is False  # 남의 팀 문서에 안 붙음
        assert r1.json()["document_id"] != r2.json()["document_id"]

    @patch("maru_lang.api.endpoints.ingest.run_ingest_for_document", new_callable=AsyncMock)
    @patch("maru_lang.services.ingest.save_upload", new_callable=AsyncMock)
    async def test_reupload_then_check_still_skips(
        self, mock_save, mock_ingest, client: AsyncClient, team_setup, tmp_path,
    ):
        """같은 파일을 두 번 upload(re-upload)한 후에도 check은 스킵해야 한다."""
        team, user = team_setup
        mock_save.return_value = "/tmp/fake/storage/memo.md"

        test_file = tmp_path / "memo.md"
        test_file.write_text("메모 내용")
        stat = test_file.stat()
        abs_path = str(test_file)
        folder_path = str(tmp_path)
        content = test_file.read_bytes()

        upload_data = {
            "team_id": str(team.id),
            "mtime": str(stat.st_mtime),
            "folder_path": folder_path,
        }

        # 첫 업로드
        await client.post(
            "/ingest/upload", headers=await auth_header(user.id),
            data=upload_data,
            files={"file": ("memo.md", io.BytesIO(content), "text/markdown")},
        )
        # 재업로드
        resp2 = await client.post(
            "/ingest/upload", headers=await auth_header(user.id),
            data=upload_data,
            files={"file": ("memo.md", io.BytesIO(content), "text/markdown")},
        )
        assert resp2.json()["is_reupload"] is True

        # check — 여전히 스킵
        check_resp = await client.post(
            "/ingest/check",
            headers=await auth_header(user.id),
            json={
                "team_id": team.id,
                "files": [
                    {"fileName": "memo.md", "absolutePath": abs_path,
                     "size": stat.st_size, "mtime": stat.st_mtime},
                ],
            },
        )
        assert check_resp.json()["indices_to_upload"] == [], \
            "재업로드 후에도 check은 스킵해야 함"
