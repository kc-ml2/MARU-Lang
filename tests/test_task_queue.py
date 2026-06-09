"""Task-queue layer: worker task dispatch + CLI token issuance (no Redis)."""
import pytest

from maru_lang.constants import ADMIN_EMAIL, INGEST_TASK_NAME
from maru_lang.core.relation_db.models.auth import User
from maru_lang.core.relation_db.models.documents import Document
from maru_lang.services import ingest as ingest_service
from maru_lang.services.cli import issue_cli_tokens
from maru_lang.worker import WorkerSettings, ingest_document_task


def test_worker_registers_ingest_task_under_constant_name():
    # Enqueue side (ingest.py) uses INGEST_TASK_NAME; the worker must register
    # the job under exactly that name or jobs silently never run.
    names = [f.name for f in WorkerSettings.functions]
    assert names == [INGEST_TASK_NAME]


async def test_ingest_task_runs_for_existing_doc(monkeypatch):
    sentinel_doc = object()
    calls = []

    async def fake_get(**kwargs):
        return sentinel_doc

    async def fake_run(doc, team_id):
        calls.append((doc, team_id))

    monkeypatch.setattr(Document, "get_or_none", fake_get)
    monkeypatch.setattr(ingest_service, "run_ingest_for_document", fake_run)

    await ingest_document_task({}, "doc_123", 7)

    assert calls == [(sentinel_doc, 7)]


async def test_ingest_task_skips_missing_doc(monkeypatch):
    ran = []

    async def fake_get(**kwargs):
        return None

    async def fake_run(doc, team_id):
        ran.append(True)

    monkeypatch.setattr(Document, "get_or_none", fake_get)
    monkeypatch.setattr(ingest_service, "run_ingest_for_document", fake_run)

    # Should no-op (deleted doc) instead of raising.
    await ingest_document_task({}, "gone", 1)

    assert ran == []


async def test_issue_cli_tokens_creates_admin_role_and_teams():
    out = await issue_cli_tokens(["public", "sales"])

    assert out["chat_token"] and out["access_token"]
    assert out["user_id"]
    assert {t["name"] for t in out["teams"]} == {"public", "sales"}

    admin = await User.get(email=ADMIN_EMAIL)
    assert admin.id == out["user_id"]
    assert admin.role_id is not None  # ADMIN role ensured


async def test_issue_cli_tokens_empty_teams():
    out = await issue_cli_tokens([])
    assert out["teams"] == []
    assert out["chat_token"] and out["access_token"]
