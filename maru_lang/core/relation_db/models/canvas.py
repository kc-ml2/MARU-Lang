"""Document-authoring (doc) graph persistence: Canvas + CanvasVersion.

A Canvas is one authored structured document (a contract, a 기안서, …) produced
by the `doc` graph and grounded on internal team docs. It is a *tree*
(sections → blocks), not a flat list, and it is versioned: every applied edit
appends an immutable CanvasVersion snapshot rather than mutating rows.

Design (event-sourcing-lite, document-oriented):
    - ``Canvas`` holds identity + listing metadata + a ``head_version_id`` pointer.
    - ``CanvasVersion`` holds the whole tree as one JSON ``payload``
      ({metadata, sections, missing_terms}). block_id/section_id live *inside*
      that JSON for addressing during the edit loop — they are never DB rows.

Why snapshots instead of normalized section/block tables: the canvas is always
read and written whole (the client renders the entire side panel), the tree is
awkward to normalize, and versioning a tree by row-diffing is painful. A whole-
payload snapshot per version is trivial and gives history/undo/lineage for free.
A canvas is small (tens of KB) and versions are human-paced, so storage is cheap.

The DB is the durable source of truth (the LangGraph checkpointer only holds the
in-flight interrupt thread): a dropped connection reloads the head version and
resumes editing in a fresh thread.
"""
from tortoise.models import Model
from tortoise import fields

from maru_lang.enums.chat import CanvasStatus

__all__ = ["Canvas", "CanvasVersion"]


class Canvas(Model):
    """An authored structured document's identity + current-version pointer.

    The tree itself lives in CanvasVersion.payload; this row is the stable
    handle the client and the graph address by ``canvas_id``.
    """
    id = fields.CharField(pk=True, max_length=64)  # = canvas_id, uuid4().hex
    user = fields.ForeignKeyField(
        "models.User", related_name="canvases", on_delete=fields.CASCADE, index=True)
    session = fields.ForeignKeyField(
        "models.Session", related_name="canvases", on_delete=fields.CASCADE,
        null=True, index=True)
    # 주 그라운딩 팀. 팀이 지워져도 문서는 보존(SET_NULL).
    team = fields.ForeignKeyField(
        "models.Team", related_name="canvases", on_delete=fields.SET_NULL, null=True)
    canvas_type = fields.CharField(max_length=64, null=True)     # "contract" / "기안서" / ...
    schema_version = fields.CharField(max_length=32, null=True)  # "contract.v1"
    title = fields.CharField(max_length=255, null=True)
    status = fields.IntEnumField(CanvasStatus, default=CanvasStatus.DRAFTING)
    instruction = fields.TextField(null=True)              # 원 요청("계약서 초안 작성해줘")
    # 현재 버전 pointer. CanvasVersion.id를 가리키되 순환 FK를 피하려 일반 컬럼.
    head_version_id = fields.CharField(max_length=64, null=True)
    references = fields.JSONField(default=list)            # 그라운딩에 사용된 청크 dicts(감사용)
    metadata = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:  # type: ignore
        table = "canvas"
        ordering = ["-updated_at"]


class CanvasVersion(Model):
    """An immutable snapshot of a Canvas's full tree at one point in its lineage.

    ``payload`` is the whole document ({metadata, sections, missing_terms}).
    ``base_version_id`` links to the predecessor it was derived from (null for
    the first draft); ``op`` records the edit that produced this version (audit).
    """
    id = fields.CharField(pk=True, max_length=64)  # = version_id, uuid4().hex
    canvas = fields.ForeignKeyField(
        "models.Canvas", related_name="versions", on_delete=fields.CASCADE, index=True)
    base_version_id = fields.CharField(max_length=64, null=True)  # 계보(이전 버전)
    op = fields.JSONField(null=True)              # 이 버전을 만든 편집 op(audit)
    payload = fields.JSONField(default=dict)      # {metadata, sections, missing_terms}
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore
        table = "canvas_version"
        ordering = ["created_at"]
