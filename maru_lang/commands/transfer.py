"""
Transfer 명령어: DocumentGroup 관리자 권한 이전
"""
import typer
from maru_lang.core.relation_db.models.documents import DocumentGroup
from maru_lang.core.relation_db.models.auth import User


async def transfer_function(
    group_name: str,
    new_manager_email: str,
    force: bool = False,
):
    """
    DocumentGroup의 관리자를 다른 사용자로 이전

    Args:
        group_name: 관리자를 변경할 DocumentGroup 이름
        new_manager_email: 새 관리자의 이메일 주소
        force: 확인 없이 강제 이전
    """
    # ========== 1. DocumentGroup 확인 ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("🔄 DocumentGroup 관리자 이전", fg=typer.colors.CYAN, bold=True)
    typer.echo("=" * 50)

    group = await DocumentGroup.get_or_none(name=group_name).prefetch_related("manager")
    if not group:
        typer.secho(
            f"❌ DocumentGroup '{group_name}'을 찾을 수 없습니다.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # ========== 2. 새 관리자 확인 ==========
    new_manager = await User.get_or_none(email=new_manager_email)
    if not new_manager:
        typer.secho(
            f"❌ 사용자 '{new_manager_email}'을 찾을 수 없습니다.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)

    # ========== 3. 현재 관리자 정보 출력 ==========
    current_manager = group.manager
    if current_manager:
        typer.echo(f"\n현재 관리자: {current_manager.name} ({current_manager.email})")
    else:
        typer.echo(f"\n현재 관리자: 없음")

    typer.echo(f"새 관리자: {new_manager.name} ({new_manager.email})")

    # 이미 같은 관리자인 경우
    if current_manager and current_manager.id == new_manager.id:
        typer.secho(
            f"\n⚠️  '{new_manager_email}'은 이미 이 그룹의 관리자입니다.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(0)

    # ========== 4. 확인 ==========
    if not force:
        typer.echo("\n" + "=" * 50)
        confirm = typer.confirm(
            f"\n'{group_name}'의 관리자를 '{new_manager_email}'로 변경하시겠습니까?"
        )
        if not confirm:
            typer.secho("\n❌ 이전 작업이 취소되었습니다.", fg=typer.colors.RED)
            raise typer.Exit(0)

    # ========== 5. 관리자 변경 ==========
    group.manager = new_manager
    await group.save()

    # ========== 완료 ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("✅ 관리자 이전 완료!", fg=typer.colors.GREEN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"DocumentGroup: {group_name}")
    typer.echo(f"새 관리자: {new_manager.name} ({new_manager.email})")
    typer.echo()
