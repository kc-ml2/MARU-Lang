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


async def test_issue_cli_tokens_joins_existing_teams_only():
    # "public" is system-bootstrapped; "sales" must pre-exist (CLI never creates).
    from maru_lang.services.admin import get_or_create_admin_user
    from maru_lang.services.team import get_or_create_team

    admin = await get_or_create_admin_user()
    await get_or_create_team(name="sales", manager=admin)

    out = await issue_cli_tokens(["public", "sales"])

    assert out["chat_token"] and out["access_token"]
    assert out["user_id"]
    assert {t["name"] for t in out["teams"]} == {"public", "sales"}

    admin = await User.get(email=ADMIN_EMAIL)
    assert admin.id == out["user_id"]
    assert admin.role_id is not None  # ADMIN role ensured


async def test_issue_cli_tokens_rejects_unknown_team():
    # A typo must NOT silently create an empty team — it fails, naming the
    # missing team and listing what exists.
    from maru_lang.core.relation_db.models.auth import Team

    with pytest.raises(ValueError, match="salse"):
        await issue_cli_tokens(["salse"])  # typo of "sales"

    assert await Team.get_or_none(name="salse") is None  # nothing created


async def test_issue_cli_tokens_empty_teams():
    out = await issue_cli_tokens([])
    assert out["teams"] == []
    assert out["chat_token"] and out["access_token"]
