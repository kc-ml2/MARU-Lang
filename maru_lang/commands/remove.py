"""
Remove 명령어: DocumentGroup 및 관련 데이터 삭제
"""
import typer
import shutil
from pathlib import Path
from typing import List

from maru_lang.core.relation_db.models.documents import (
    DocumentGroup,
    Document,
    DocumentGroupMembership,
    DocumentGroupInclusion,
    GroupPermission,
)
from maru_lang.services.document import get_all_descendant_group_ids
from maru_lang.core.vector_db.factory import get_vector_db


async def remove_function(
    group_name: str,
    force: bool = False,
):
    """
    DocumentGroup과 모든 하위 그룹, 문서, 임베딩 삭제

    Args:
        group_name: 삭제할 DocumentGroup 이름
        force: 확인 없이 강제 삭제
    """
    # ========== 1. DocumentGroup 확인 ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("🗑️  DocumentGroup 삭제", fg=typer.colors.RED, bold=True)
    typer.echo("=" * 50)

    group = await DocumentGroup.get_or_none(name=group_name).prefetch_related("manager")
    if not group:
        typer.secho(
            f"❌ DocumentGroup '{group_name}'을 찾을 수 없습니다.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # ========== 2. Manager 확인 (삭제 보호) ==========
    if group.manager:
        typer.echo("\n" + "=" * 50)
        typer.secho(
            "🛡️  삭제 보호: 이 DocumentGroup에는 관리자가 지정되어 있습니다!",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.echo("=" * 50)
        typer.echo(f"   관리자: {group.manager.name} ({group.manager.email})")
        typer.echo("\n관리자가 있는 DocumentGroup은 삭제할 수 없습니다.")
        typer.echo("삭제하려면 먼저 다음 방법 중 하나를 선택하세요:")
        typer.echo("  1. 다른 사용자에게 관리자 권한 이전:")
        typer.echo(f"     maru transfer {group_name} <new_manager_email>")
        typer.echo("  2. 관리자 제거 (권장하지 않음):")
        typer.echo(f"     maru unmanage {group_name}")
        typer.echo()
        raise typer.Exit(1)

    # ========== 2. 하위 그룹 및 문서 수집 ==========
    typer.echo(f"\n📊 삭제 대상 분석 중...")

    # 하위 그룹 포함 모든 그룹 ID 수집
    all_group_ids = await get_all_descendant_group_ids([group.id])
    all_group_ids.add(group.id)

    # 모든 그룹 정보 가져오기
    all_groups = await DocumentGroup.filter(id__in=list(all_group_ids)).all()
    group_names = [g.name for g in all_groups]

    # 모든 문서 수집
    all_documents = (
        await Document.filter(
            group_memberships__group_id__in=list(all_group_ids)
        )
        .distinct()
        .all()
    )

    # ========== 3. 삭제 정보 출력 ==========
    typer.echo("\n📋 삭제될 항목:")
    typer.echo(f"   DocumentGroup: {len(all_groups)}개")
    for name in group_names:
        typer.echo(f"      - {name}")
    typer.echo(f"   Documents: {len(all_documents)}개")
    typer.echo(f"   VectorDB: 단일 backend에서 청크 삭제 예정")

    # ========== 4. 확인 ==========
    if not force:
        typer.echo("\n" + "=" * 50)
        typer.secho(
            "⚠️  경고: 이 작업은 되돌릴 수 없습니다!",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.echo("=" * 50)

        confirm = typer.confirm(
            f"\n정말로 '{group_name}'과 모든 관련 데이터를 삭제하시겠습니까?"
        )
        if not confirm:
            typer.secho("\n❌ 삭제 작업이 취소되었습니다.", fg=typer.colors.RED)
            raise typer.Exit(0)

    # ========== 5. VDB에서 임베딩 삭제 ==========
    if all_documents:
        typer.echo("\n🗑️  VectorDB에서 임베딩 삭제 중...")
        try:
            # VectorDB 인스턴스 생성 (settings 기본값 사용)
            vdb = get_vector_db()

            total_deleted = 0
            for doc in all_documents:
                deleted_count = vdb.delete_all_chunks_by_document_id(doc.id)
                total_deleted += deleted_count

            typer.secho(
                f"   ✓ {len(all_documents)}개 문서의 {total_deleted}개 청크 삭제 완료",
                fg=typer.colors.GREEN,
            )
        except Exception as e:
            typer.secho(
                f"   ⚠️  VDB 임베딩 삭제 실패: {e}",
                fg=typer.colors.YELLOW,
            )
            typer.echo("   RDB 삭제는 계속 진행됩니다.")

    # ========== 6. RDB 레코드 삭제 ==========
    typer.echo("\n🗑️  데이터베이스 레코드 삭제 중...")

    # 6-1. GroupPermission 삭제
    deleted_perms = await GroupPermission.filter(
        document_group_id__in=list(all_group_ids)
    ).delete()
    typer.echo(f"   ✓ 권한 레코드: {deleted_perms}개")

    # 6-2. DocumentGroupMembership 삭제
    deleted_memberships = await DocumentGroupMembership.filter(
        group_id__in=list(all_group_ids)
    ).delete()
    typer.echo(f"   ✓ 문서-그룹 관계: {deleted_memberships}개")

    # 6-3. Documents 삭제
    deleted_docs = await Document.filter(
        group_memberships__group_id__in=list(all_group_ids)
    ).delete()
    typer.echo(f"   ✓ 문서: {deleted_docs}개")

    # 6-4. DocumentGroupInclusion 삭제 (부모-자식 관계)
    deleted_inclusions = await DocumentGroupInclusion.filter(
        parent_id__in=list(all_group_ids)
    ).delete()
    deleted_inclusions += await DocumentGroupInclusion.filter(
        child_id__in=list(all_group_ids)
    ).delete()
    typer.echo(f"   ✓ 그룹 계층 관계: {deleted_inclusions}개")

    # 6-5. DocumentGroup 삭제
    deleted_groups = await DocumentGroup.filter(id__in=list(all_group_ids)).delete()
    typer.echo(f"   ✓ DocumentGroup: {deleted_groups}개")

    # ========== 완료 ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("✅ 삭제 완료!", fg=typer.colors.GREEN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"📊 삭제된 항목:")
    typer.echo(f"   DocumentGroup: {deleted_groups}개")
    typer.echo(f"   Documents: {deleted_docs}개")
    typer.echo(f"   임베딩: {len(all_documents) if all_documents else 0}개")
    typer.echo()
