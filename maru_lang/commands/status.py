"""
status 명령어: RDB와 VectorDB의 현재 상태 출력
"""
import typer
from collections import defaultdict
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
)
from maru_lang.core.relation_db.models.auth import (
    UserGroup,
    UserGroupMembership,
)
from maru_lang.enums.documents import DocumentStatus


async def show_status(verbose: bool = False):
    """RDB와 VectorDB의 상태를 조회하고 출력"""

    typer.echo("=" * 60)
    typer.echo("📊 System Status")
    typer.echo("=" * 60)

    # ========================================
    # 1. RDB 상태
    # ========================================
    typer.echo("\n🗄️  Relational Database (RDB)")
    typer.echo("-" * 60)

    # Document 상태별 개수
    total_docs = await Document.all().count()
    processing_docs = await Document.filter(status=DocumentStatus.PROCESSING).count()
    active_docs = await Document.filter(status=DocumentStatus.ACTIVE).count()
    inactive_docs = await Document.filter(status=DocumentStatus.INACTIVE).count()

    typer.echo(f"\n📄 Documents: {total_docs} total")
    typer.echo(f"   • PROCESSING: {processing_docs}")
    typer.echo(f"   • ACTIVE:     {active_docs}")
    typer.echo(f"   • INACTIVE:   {inactive_docs}")

    # DocumentGroup 개수 및 상세 정보
    total_groups = await DocumentGroup.all().count()
    typer.echo(f"\n🏷️  Document Groups: {total_groups}")

    if verbose and total_groups > 0:
        # 각 그룹별 문서 개수 및 inclusion 정보
        doc_groups = await DocumentGroup.all()
        for group in doc_groups:
            doc_count = await DocumentGroupMembership.filter(group=group).count()

            # 이 그룹이 포함(include)하는 다른 그룹들
            inclusions = await DocumentGroupInclusion.filter(parent=group).prefetch_related('child')
            included_names = [inc.child.name for inc in inclusions]

            typer.echo(f"   • {group.name}: {doc_count} documents")
            if included_names:
                typer.echo(f"      includes: {', '.join(included_names)}")
    elif total_groups > 0:
        typer.echo("   (Use --verbose to see group details)")

    # UserGroup 개수 및 상세 정보
    total_user_groups = await UserGroup.all().count()
    typer.echo(f"\n👥 User Groups: {total_user_groups}")

    if verbose and total_user_groups > 0:
        # 각 그룹별 멤버 수
        user_groups = await UserGroup.all()
        for group in user_groups:
            member_count = await UserGroupMembership.filter(group=group).count()
            typer.echo(f"   • {group.name}: {member_count} members")
    elif total_user_groups > 0:
        typer.echo("   (Use --verbose to see group details)")

    # ========================================
    # 2. VectorDB 통계 (단일 backend, 그룹별 집계)
    # ========================================
    typer.echo("\n\n📊 Vector Database Statistics")
    typer.echo("-" * 60)

    vdb_stats_total = {"documents": 0, "chunks": 0}

    try:
        # VectorDB 인스턴스 생성 (settings 기본값 사용)
        from maru_lang.core.vector_db.factory import get_vector_db

        vdb = get_vector_db()

        # 그룹별 통계 집계
        collection_data = vdb.get_all_metadata()
        stats = {}

        for meta in collection_data:
            group = meta.get("group", "unknown")
            doc_id = meta.get("document_id", "unknown")

            if group not in stats:
                stats[group] = {
                    "documents": set(),
                    "chunks": 0
                }

            stats[group]["documents"].add(doc_id)
            stats[group]["chunks"] += 1

        # set을 숫자로 변환
        for group in stats:
            stats[group]["documents"] = len(stats[group]["documents"])

        if not stats:
            typer.echo("\n⚠️  No data in vector databases")
        else:
            # 전체 통계
            total_vdb_docs = sum(s["documents"] for s in stats.values())
            total_vdb_chunks = sum(s["chunks"] for s in stats.values())

            vdb_stats_total["documents"] = total_vdb_docs
            vdb_stats_total["chunks"] = total_vdb_chunks

            typer.echo(f"\n📊 Total: {total_vdb_docs} documents, {total_vdb_chunks} chunks")

            # 그룹별 통계
            if verbose:
                typer.echo("\n📑 By Group:")
                for group_name, group_stats in sorted(stats.items()):
                    typer.echo(f"   • {group_name}:")
                    typer.echo(f"      - Documents: {group_stats['documents']}")
                    typer.echo(f"      - Chunks:    {group_stats['chunks']}")
            else:
                typer.echo(f"\n📑 Groups: {len(stats)}")
                typer.echo("   (Use --verbose to see group details)")

    except Exception as e:
        typer.secho(f"\n❌ Error accessing VectorDB: {e}", fg=typer.colors.RED)
        vdb_stats_total = None

    # ========================================
    # 3. 일관성 검사
    # ========================================
    typer.echo("\n\n🔍 Consistency Check")
    typer.echo("-" * 60)

    issues_found = False

    # RDB ACTIVE documents vs VectorDB documents 비교
    if vdb_stats_total:
        rdb_active = active_docs
        vdb_docs = vdb_stats_total["documents"]

        consistency_ok = abs(rdb_active - vdb_docs) < 5  # 약간의 오차 허용

        if consistency_ok:
            typer.secho(
                f"\n✅ RDB ACTIVE documents ({rdb_active}) ≈ VectorDB documents ({vdb_docs})",
                fg=typer.colors.GREEN
            )
        else:
            typer.secho(
                f"\n⚠️  Inconsistency detected:",
                fg=typer.colors.YELLOW
            )
            typer.echo(f"   RDB ACTIVE documents:  {rdb_active}")
            typer.echo(f"   VectorDB documents:    {vdb_docs}")
            typer.echo(f"   Difference:            {abs(rdb_active - vdb_docs)}")
            typer.echo("\n   Consider re-running: chatbot ingest")
            issues_found = True

    # PROCESSING 문서 확인
    if processing_docs > 0:
        typer.secho(
            f"\n⚠️  {processing_docs} documents are PROCESSING (incomplete ingest)",
            fg=typer.colors.YELLOW
        )
        typer.echo("   Re-run: chatbot ingest to complete")
        issues_found = True

    # INACTIVE 문서 확인
    if inactive_docs > 0:
        typer.secho(
            f"\n⚠️  {inactive_docs} documents are INACTIVE",
            fg=typer.colors.YELLOW
        )
        issues_found = True

    # 요약
    typer.echo("\n" + "=" * 60)
    if not issues_found:
        typer.secho("✅ System is healthy!", fg=typer.colors.GREEN)
    else:
        typer.secho("⚠️  Some issues found. See recommendations above.", fg=typer.colors.YELLOW)
    typer.echo("=" * 60)
