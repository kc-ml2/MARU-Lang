"""
Ingest 명령어: IngestPipeline을 사용한 파일 ingest
"""
import typer
from typing import List, Optional
from pathlib import Path

from maru_lang.pipelines.ingest import IngestPipeline
from maru_lang.pipelines.base import PipelineMessage, PipelineComplete, MessageType
from maru_lang.models.vector_db import ChromaDBConfig
from maru_lang.services.user_group import (
    link_user_groups_to_document_groups,
    validate_user_groups_exist,
)
from maru_lang.services.document import get_all_descendant_group_names
from maru_lang.core.relation_db.models.documents import PermissionAction


async def ingest_function(
    path: Path,
    user_groups: Optional[List[str]] = None,
    max_batch_size_mb: int = 1000,
    verbose: bool = False,
):
    """
    디렉토리를 ingest (파싱, 청킹, 임베딩, VDB 저장)

    Args:
        path: ingest할 디렉토리 경로 (폴더 이름이 DocumentGroup 이름으로 사용됨)
        user_groups: 권한을 부여할 UserGroup 리스트
        max_batch_size_mb: 배치당 최대 메모리 크기 (MB, 기본: 10MB)
        verbose: 자세한 출력 모드 (모든 처리되는 문서 표시)
    """
    # ========== 입력 검증 ==========
    if not path.exists() or not path.is_dir():
        typer.secho(
            f"🚫 폴더가 존재하지 않거나 유효하지 않습니다: {path}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    # 폴더 이름을 group 이름으로 사용
    group = path.name

    # ========== UserGroup 검증 및 확인 ==========
    existing_groups = []
    if user_groups is None or len(user_groups) == 0:
        typer.echo("\n" + "=" * 50)
        typer.secho(
            "⚠️  경고: UserGroup이 지정되지 않았습니다!",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        typer.secho(
            "   문서가 생성되지만 어떤 사용자 그룹도 접근할 수 없습니다.",
            fg=typer.colors.YELLOW,
        )
        typer.echo("=" * 50)

        confirm = typer.confirm("UserGroup 없이 계속 진행하시겠습니까?")
        if not confirm:
            typer.secho("\n❌ Ingest 작업이 취소되었습니다.", fg=typer.colors.RED)
            raise typer.Exit(0)
        typer.echo()
    else:
        # UserGroup 검증
        existing_groups, missing_groups = await validate_user_groups_exist(user_groups)

        if missing_groups:
            typer.echo("\n" + "=" * 50)
            typer.secho(
                f"⚠️  경고: 다음 UserGroup들이 존재하지 않습니다:",
                fg=typer.colors.YELLOW,
                bold=True,
            )
            for mg in missing_groups:
                typer.secho(f"   - {mg}", fg=typer.colors.YELLOW)
            typer.echo("=" * 50)

            if not existing_groups:
                typer.secho(
                    "\n❌ 유효한 UserGroup이 없습니다. 작업을 중단합니다.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(1)

            confirm = typer.confirm(
                f"존재하는 {len(existing_groups)}개 그룹으로 계속 진행하시겠습니까?"
            )
            if not confirm:
                typer.secho("\n❌ Ingest 작업이 취소되었습니다.", fg=typer.colors.RED)
                raise typer.Exit(0)
            typer.echo()

    # ========== IngestPipeline 실행 ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("🚀 Starting Ingest Pipeline", fg=typer.colors.CYAN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"📂 Path: {path}")
    typer.echo(f"📦 Group: {group}")
    typer.echo(f"🧠 Batch size: {max_batch_size_mb}MB")
    typer.echo()

    import time
    start_time = time.time()

    try:
        # ========== VectorDB 설정 ==========
        # VectorDB 설정 생성 (settings 기본값 사용, 단일 backend)
        vdb_config = ChromaDBConfig.from_settings()

        # ========== IngestPipeline 실행 (config-driven) ==========
        pipeline = IngestPipeline(
            path=path,
            group_name=group,
            vdb_config=vdb_config,
            max_batch_size_mb=max_batch_size_mb,
            verbose=verbose,
        )

        result = None
        async for item in pipeline.run():
            # 완료 신호 확인
            if isinstance(item, PipelineComplete):
                result = item.data
                break

            # PipelineMessage 처리
            if isinstance(item, PipelineMessage):
                if item.message_type == MessageType.INFO:
                    typer.secho(f"  {item.message}", fg=typer.colors.CYAN)
                elif item.message_type == MessageType.WARNING:
                    typer.secho(f"  ⚠️  {item.message}", fg=typer.colors.YELLOW)
                elif item.message_type == MessageType.ERROR:
                    typer.secho(f"  ❌ {item.message}", fg=typer.colors.RED)

        if result is None:
            raise ValueError("Pipeline did not return a result")

    except ValueError as e:
        typer.secho(f"\n❌ Ingest 실패: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"\n❌ 예상치 못한 오류: {str(e)}", fg=typer.colors.RED)
        import traceback

        traceback.print_exc()
        raise typer.Exit(1)

    # ========== UserGroup 권한 연결 ==========
    if existing_groups:
        typer.echo("\n" + "=" * 50)
        typer.secho("🔐 Linking UserGroups", fg=typer.colors.CYAN, bold=True)
        typer.echo("=" * 50)

        # 생성된 모든 DocumentGroup 이름 가져오기 (하위 그룹 포함)
        all_doc_group_names = await get_all_descendant_group_names([group])

        typer.echo(
            f"📊 Linking {len(existing_groups)} UserGroup(s) to {len(all_doc_group_names)} DocumentGroup(s)..."
        )
        typer.echo(f"   UserGroups: {', '.join(existing_groups)}")
        typer.echo(f"   Permissions: READ, WRITE, MANAGE")

        perm_result = await link_user_groups_to_document_groups(
            user_group_names=existing_groups,
            document_group_names=all_doc_group_names,
            actions=[
                PermissionAction.READ,
                PermissionAction.WRITE,
                PermissionAction.MANAGE,
            ],
            link_descendants=True,
        )

        typer.secho(
            f"✅ {perm_result['permissions_created']}개 권한 생성됨",
            fg=typer.colors.GREEN,
        )

    # ========== 완료 메시지 ==========
    elapsed_time = time.time() - start_time

    typer.echo("\n" + "=" * 50)
    typer.secho("✅ Ingest 완료!", fg=typer.colors.GREEN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"📊 전체 파일: {result.total_files}개")
    typer.echo(f"✅ 처리됨: {result.processed_files}개 (신규 또는 수정됨)")
    typer.echo(f"⏭️  스킵됨: {result.skipped_files}개 (변경 없음)")
    typer.echo(f"📦 DocumentGroup: {result.group.name}")
    typer.echo(f"⏱️  소요 시간: {elapsed_time:.2f}초")
    typer.secho(
        "🎉 모든 문서가 임베딩되어 검색 가능합니다!", fg=typer.colors.GREEN
    )
    typer.echo()
