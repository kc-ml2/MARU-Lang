import sys
import os
import re
import typer
import uvicorn
import subprocess
from pathlib import Path
from typing import Optional, List
from maru_lang.core.settings import settings
from maru_lang.core.relation_db.connection import run_with_orm_context
from maru_lang.commands.ingest import ingest_function
from maru_lang.commands.remove import remove_function
from maru_lang.commands.install import install_configs
from maru_lang.commands.chat import chat_session
from maru_lang.commands.status import show_status
from maru_lang.commands.tree import show_group_tree_command



app = typer.Typer()

@app.command()
def serve(
    app_module: str = typer.Argument("main:app",
                                     help="앱 모듈 경로 (기본: main:app)"),
    host: str = typer.Option(None, help="서버 host"),
    port: int = typer.Option(None, help="서버 port"),
    reload: bool = typer.Option(None, help="코드 변경 감지 reload"),
    log_level: str = typer.Option(None, help="로그 레벨"),
    workers: int = typer.Option(1, help="서버 워커 수"),
):
    """Start the chatbot FastAPI server (default: maru_app/main.py)"""

    # Check if installation is complete
    _check_maru_app_installation()

    # Add current directory and maru_app to Python path
    if '.' not in sys.path:
        sys.path.insert(0, os.getcwd())

    # Add maru_app to path if it exists
    maru_app_path = os.path.join(os.getcwd(), 'maru_app')
    if os.path.exists(maru_app_path) and maru_app_path not in sys.path:
        sys.path.insert(0, maru_app_path)

    # CLI 인자로 오버라이드
    host = host or settings.HOST
    port = port or settings.PROT
    reload = reload if reload is not None else settings.RELOAD
    log_level = log_level or settings.LOG_LEVEL

    # reload와 workers 충돌 체크
    if workers > 1 and reload:
        typer.echo("⚠️  경고: reload 모드에서는 멀티 워커를 사용할 수 없습니다.")
        typer.echo("   개발 시: --reload 사용 (단일 워커, 코드 변경 감지)")
        typer.echo("   프로덕션 시: --workers N 사용 (멀티 워커, reload 비활성화)")
        typer.echo("   → workers를 1로 조정하고 reload 모드로 실행합니다.")
        workers = 1

    # 앱 모듈 경로 확인
    if ":" not in app_module:
        typer.echo(
            f"❌ Error: App module must be in format 'module:variable' (예: main:app)")
        raise typer.Exit(1)

    module_part, var_part = app_module.split(":", 1)

    # 모듈 파일 존재 여부 확인 (현재 디렉토리 -> maru_app 순서로 탐색)
    module_file = Path(f"{module_part.replace('.', '/')}.py")
    maru_app_file = Path(f"maru_app/{module_part.replace('.', '/')}.py")

    target_app_module = app_module

    if module_file.exists():
        typer.echo(f"🎯 Running app: {app_module}")
    elif maru_app_file.exists():
        # maru_app에서 찾은 경우 모듈 경로 수정
        target_app_module = f"maru_app.{module_part}:{var_part}"
        typer.echo(f"🎯 Running app from maru_app: {target_app_module}")
    else:
        typer.echo(
            f"⚠️  Warning: Module file not found in current directory or maru_app/")
        typer.echo(f"   Attempting to run: {app_module}")

    typer.echo(
        f"🚀 Running on {host}:{port} (workers={workers}, reload={reload})")

    if workers > 1:
        # 멀티 워커는 subprocess로 uvicorn CLI 실행
        typer.echo("🔧 프로덕션 모드: 멀티 워커로 실행")

        # Set PYTHONPATH to include current directory
        # env = os.environ.copy()
        # if 'PYTHONPATH' in env:
        #     env['PYTHONPATH'] = f"{os.getcwd()}{os.pathsep}{env['PYTHONPATH']}"
        # else:
        #     env['PYTHONPATH'] = os.getcwd()

        cmd = [
            "uvicorn",
            target_app_module,
            "--host", host,
            "--port", str(port),
            "--workers", str(workers),
            "--log-level", log_level,
        ]
        typer.echo(f"   실행 명령어: {' '.join(cmd)}")
        subprocess.run(cmd)

        # subprocess.run(cmd, env=env)
    else:
        # 단일 워커는 기존 방식
        if reload:
            typer.echo("🔧 개발 모드: 단일 워커 + 코드 변경 감지")
        else:
            typer.echo("🔧 단일 워커 모드: 코드 변경 감지 비활성화")

        uvicorn.run(
            target_app_module,
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
        )


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="문서가 들어있는 폴더 경로"),
    user_groups: Optional[List[str]] = typer.Option(
        None, "--user-group", "-ug", help="문서 그룹에 접근 권한을 부여할 사용자 그룹 (여러 개 지정 가능)"),
    batch_size: int = typer.Option(
        1000, "--batch-size", "-b", help="배치당 최대 메모리 크기 (MB, 기본: 1000MB)"),
):
    """폴더 내 모든 문서를 파싱하여 청킹 및 DB 저장"""
    group = path.name

    if not path.exists() or not path.is_dir():
        typer.echo(f"❌ {path} 폴더가 존재하지 않습니다.")
        raise typer.Exit(1)

    # group 정규식 검사 ( / 이런 특수문자 포함 불가)
    if not re.match(r'^[a-zA-Z0-9_]+$', group):
        typer.echo(f"❌ {group} 그룹은 영문, 숫자, 언더스코어(_)만 사용 가능합니다.")
        raise typer.Exit(1)

    typer.echo(
        f"🚀 Ingesting {path} with group {group}")

    run_with_orm_context(
        ingest_function,
        path,
        user_groups,
        batch_size,
    )


@app.command()
def remove(
    group: str = typer.Argument(..., help="삭제할 DocumentGroup 이름"),
    force: bool = typer.Option(
        False, "--force", "-f", help="확인 없이 강제 삭제"
    ),
):
    """DocumentGroup과 모든 관련 데이터 삭제 (문서, 임베딩, VDB)"""
    typer.echo(f"🗑️  Removing DocumentGroup: {group}")

    run_with_orm_context(remove_function, group, force)


@app.command()
def chat(
    groups: Optional[str] = typer.Option(
        "all", "--group", "-g",
        help="Document groups to search (e.g., -g engineering,docs or -g all)"
    ),
    max_turns: int = typer.Option(
        0, "--max-turns", "-m",
        help="Maximum number of turns to keep in chat history"
    )
):
    """Start an interactive admin chat session with document group selection"""

    # Check if installation is complete
    _check_maru_app_installation()

    # 그룹 파싱
    if groups == "all":
        # 모든 그룹 검색
        parsed_groups = ["__all__"]  # None은 모든 그룹을 의미
    else:
        # 쉼표로 구분된 그룹들
        parsed_groups = [g.strip() for g in groups.split(",")]

    # ORM 컨텍스트와 함께 실행 (문서 검색 등을 위해 DB 접근 필요)
    run_with_orm_context(chat_session, parsed_groups, max_turns)


@app.command("install")
def install(
    path: Optional[Path] = typer.Option(
        None, "--path", "-p",
        help="Custom installation path (default: current directory)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Overwrite existing files"
    ),
):
    """Initialize configuration directories with sample files"""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()

    console.print(Panel.fit(
        "[bold cyan]LLM Chatbot Configuration Installer[/bold cyan]\n"
        "This will create configuration directories and sample files.",
        border_style="cyan"
    ))

    # Confirm if not forcing
    if not force:
        if path:
            target = str(path)
        else:
            target = "current directory"

        confirm = typer.confirm(f"Install configuration files to {target}?")
        if not confirm:
            console.print("Installation cancelled.")
            raise typer.Exit(0)

    # Run installation
    success = install_configs(path, force)

    if not success:
        raise typer.Exit(1)


@app.command()
def status(
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="자세한 정보 출력 (그룹별 통계 등)"
    ),
):
    """RDB와 VectorDB의 현재 상태 확인"""
    run_with_orm_context(show_status, verbose)


@app.command()
def tree(
    name: Optional[str] = typer.Argument(
        None, help="DocumentGroup 이름 (없으면 루트 그룹들만 표시)"),
    depth: int = typer.Option(2, "--depth", "-d", help="표시할 최대 깊이 (기본: 2)"),
):
    """DocumentGroup 계층 구조 조회"""
    run_with_orm_context(show_group_tree_command, name, depth)

def _check_maru_app_installation() -> bool:
    """Check if required files exist and guide user to install if not"""
    maru_app_path = Path.cwd() / "maru_app"
    main_py = maru_app_path / "main.py"
    build_selector = maru_app_path / "build_selector.yaml"

    missing_items = []

    if not maru_app_path.exists():
        missing_items.append("maru_app/ directory")
    else:
        if not main_py.exists():
            missing_items.append("maru_app/main.py")
        if not build_selector.exists():
            missing_items.append("maru_app/build_selector.yaml")

    if missing_items:
        typer.echo("❌ Error: Installation incomplete!")
        typer.echo("")
        typer.echo("Missing files:")
        for item in missing_items:
            typer.echo(f"  - {item}")
        typer.echo("")
        typer.echo(
            "💡 Please run the following command to initialize your project:")
        typer.echo("   chatbot install")
        typer.echo("")
        raise typer.Exit(1)

    return True