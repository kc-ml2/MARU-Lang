"""
DocumentGroup 계층 구조 조회 및 관리 명령어
"""
import typer
from typing import Optional
from maru_lang.core.relation_db.models.documents import (
    DocumentGroup,
    DocumentGroupInclusion,
)


async def get_root_groups() -> list[DocumentGroup]:
    """
    루트 그룹들을 조회 (DocumentGroupInclusion에서 child로 지정되지 않은 그룹)

    Returns:
        루트 DocumentGroup 리스트
    """
    # child_id로 사용된 그룹 ID들
    child_ids = await DocumentGroupInclusion.all().values_list("child_id", flat=True)
    child_ids_set = set(child_ids)

    # 모든 그룹 조회
    all_groups = await DocumentGroup.all()

    # child로 지정되지 않은 그룹만 필터링 (루트 그룹)
    root_groups = [g for g in all_groups if g.id not in child_ids_set]

    return sorted(root_groups, key=lambda g: g.name)


async def get_children_groups(parent_group: DocumentGroup) -> list[DocumentGroup]:
    """
    특정 그룹의 직계 자식 그룹들을 조회

    Args:
        parent_group: 부모 그룹

    Returns:
        자식 DocumentGroup 리스트
    """
    inclusions = await DocumentGroupInclusion.filter(
        parent=parent_group
    ).prefetch_related("child")

    children = [inc.child for inc in inclusions]
    return sorted(children, key=lambda g: g.name)


async def print_group_tree(
    group: DocumentGroup | None = None,
    max_depth: int = 2,
    current_depth: int = 0,
    prefix: str = "",
    is_last: bool = True
):
    """
    그룹 계층 구조를 트리 형태로 출력

    Args:
        group: 출력할 그룹 (None이면 루트부터)
        max_depth: 최대 깊이
        current_depth: 현재 깊이
        prefix: 출력 prefix (트리 그리기용)
        is_last: 마지막 자식인지 여부
    """
    if group is None:
        # 루트 그룹들 출력
        root_groups = await get_root_groups()

        if not root_groups:
            typer.secho("📭 DocumentGroup이 없습니다.", fg=typer.colors.YELLOW)
            return

        typer.echo("\n📁 Document Group 계층 구조:\n")
        for i, root in enumerate(root_groups):
            is_last_root = (i == len(root_groups) - 1)
            await print_group_tree(root, max_depth, 0, "", is_last_root)
    else:
        # 현재 그룹 출력
        if current_depth == 0:
            connector = ""
            typer.secho(f"{group.name}", fg=typer.colors.CYAN, bold=True)
        else:
            connector = "└── " if is_last else "├── "
            typer.secho(f"{prefix}{connector}{group.name}", fg=typer.colors.GREEN)

        # 최대 깊이에 도달하면 중단
        if current_depth >= max_depth:
            return

        # 자식 그룹들 재귀 출력
        children = await get_children_groups(group)

        for i, child in enumerate(children):
            is_last_child = (i == len(children) - 1)

            if current_depth == 0:
                child_prefix = ""
            else:
                child_prefix = prefix + ("    " if is_last else "│   ")

            await print_group_tree(
                child,
                max_depth,
                current_depth + 1,
                child_prefix,
                is_last_child
            )


async def show_group_tree_command(
    group_name: Optional[str] = None,
    depth: int = 2
):
    """
    DocumentGroup 계층 구조 출력 명령어

    Args:
        group_name: 특정 그룹명 (없으면 루트 그룹들만 표시)
        depth: 표시할 최대 깊이
    """
    if group_name:
        # 특정 그룹 조회
        group = await DocumentGroup.get_or_none(name=group_name.lower())

        if not group:
            typer.secho(
                f"❌ '{group_name}' 그룹을 찾을 수 없습니다.",
                fg=typer.colors.RED
            )
            raise typer.Exit(1)

        typer.echo(f"\n📁 '{group.name}' 그룹 계층 구조 (depth={depth}):\n")
        await print_group_tree(group, max_depth=depth)
    else:
        # 루트 그룹들만 표시 (depth=1)
        await print_group_tree(None, max_depth=1)

    typer.echo()  # 빈 줄
