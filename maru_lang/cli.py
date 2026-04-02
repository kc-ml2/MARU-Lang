from maru_lang.commands.tree import show_group_tree_command
from maru_lang.commands.status import show_status
from maru_lang.commands.chat import chat_session
from maru_lang.commands.install import install_configs
from maru_lang.commands.transfer import transfer_function
from maru_lang.commands.remove import remove_function
from maru_lang.commands.ingest import ingest_function
from maru_lang.core.relation_db.connection import run_with_orm_context
import sys
import os
import typer
import uvicorn
import subprocess
from pathlib import Path
from typing import Optional
from maru_lang.configs import get_config

app = typer.Typer()


@app.callback()
def common_init(ctx: typer.Context):
    """Common initialization before all commands"""
    # Skip for install command (no config needed yet)
    if ctx.invoked_subcommand == "install":
        return

    # Load config (DB, auth, LLM, RAG, Agent, etc.)
    get_config()


@app.command()
def serve(
    app_module: str = typer.Argument("main:app",
                                     help="Application module path (default: main:app)"),
    host: str = typer.Option(None, help="Server host"),
    port: int = typer.Option(None, help="Server port"),
    reload: bool = typer.Option(
        None, help="Enable hot-reload when code changes"),
    log_level: str = typer.Option(None, help="Log level"),
    workers: int = typer.Option(1, help="Number of server workers"),
    skip_migrations: bool = typer.Option(
        False, "--skip-migrations", help="Skip automatic database migrations"),
):
    """Start the chatbot FastAPI server (default: maru_app/main.py)"""

    config = get_config()

    # Check if installation is complete
    _check_maru_app_installation()

    # Run migrations before starting the server
    if not skip_migrations:
        typer.echo("🔄 Checking for pending database migrations...")
        from maru_lang.core.relation_db.migration_utils import run_migrations_sync
        success = run_migrations_sync()
        if not success:
            typer.echo(
                "⚠️  Migration check failed, but continuing to start server...")
        typer.echo("")

    # Add current directory and maru_app to Python path
    if '.' not in sys.path:
        sys.path.insert(0, os.getcwd())

    # Add maru_app to path if it exists
    maru_app_path = os.path.join(os.getcwd(), 'maru_app')
    if os.path.exists(maru_app_path) and maru_app_path not in sys.path:
        sys.path.insert(0, maru_app_path)

    # Override defaults with CLI arguments when provided
    host = host or config.server.host
    port = port or config.server.port
    reload = reload if reload is not None else config.server.reload
    log_level = log_level or config.server.log_level

    # Prevent using reload with multiple workers
    if workers > 1 and reload:
        typer.echo(
            "⚠️  Warning: reload mode cannot be combined with multiple workers.")
        typer.echo(
            "   Development: use --reload (single worker with code reloading)")
        typer.echo(
            "   Production: use --workers N (multiple workers, reload disabled)")
        typer.echo("   → Adjusting workers to 1 and running in reload mode.")
        workers = 1

    # Validate module path format
    if ":" not in app_module:
        typer.echo(
            "❌ Error: App module must be in format 'module:variable' (e.g., main:app)")
        raise typer.Exit(1)

    module_part, var_part = app_module.split(":", 1)

    # Check whether the module file exists (current directory first, then maru_app)
    module_file = Path(f"{module_part.replace('.', '/')}.py")
    maru_app_file = Path(f"maru_app/{module_part.replace('.', '/')}.py")

    target_app_module = app_module

    if module_file.exists():
        typer.echo(f"🎯 Running app: {app_module}")
    elif maru_app_file.exists():
        # If found under maru_app, adjust module path accordingly
        target_app_module = f"maru_app.{module_part}:{var_part}"
        typer.echo(f"🎯 Running app from maru_app: {target_app_module}")
    else:
        typer.echo(
            "⚠️  Warning: Module file not found in the current directory or maru_app/")
        typer.echo(f"   Attempting to run: {app_module}")

    typer.echo(
        f"🚀 Running on {host}:{port} (workers={workers}, reload={reload})")

    if workers > 1:
        # Execute uvicorn CLI in a subprocess for multi-worker mode
        typer.echo("🔧 Production mode: running with multiple workers")

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
        typer.echo(f"   Command: {' '.join(cmd)}")
        subprocess.run(cmd)

        # subprocess.run(cmd, env=env)
    else:
        if reload:
            typer.echo("🔧 Development mode: single worker with code reloading")
        else:
            typer.echo("🔧 Single worker mode: reload disabled")

        uvicorn.run(
            target_app_module,
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
        )


@app.command()
def ingest(
    path: Path = typer.Argument(...,
                                help="Folder path that contains documents"),
    team: str = typer.Argument(...,
                               help="Team name that will own the documents"),
    re_embed: bool = typer.Option(
        False, "--re-embed", "-r", help="Delete existing embeddings and re-embed all documents from scratch"),
):
    """Parse every document in the folder, chunk it, and store it in the database."""
    if not path.exists() or not path.is_dir():
        typer.echo(f"Path does not exist: {path}")
        raise typer.Exit(1)

    typer.echo(f"Ingesting {path} for team '{team}'")

    run_with_orm_context(
        ingest_function,
        path,
        team,
        re_embed,
    )


@app.command()
def remove(
    group: str = typer.Argument(..., help="DocumentGroup name to delete"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Delete without confirmation"
    ),
):
    """Delete a DocumentGroup and all associated data (documents, embeddings, VDB)."""
    typer.echo(f"🗑️  Removing document group: {group}")

    run_with_orm_context(remove_function, group, force)


@app.command()
def chat(
    teams: str = typer.Argument(...,
                                help="Team names (comma-separated, e.g. 'team1,team2')"),
    max_turns: int = typer.Option(
        0, "--max-turns", "-m",
        help="Maximum number of turns to keep in chat history"
    ),
    skip_migrations: bool = typer.Option(
        False, "--skip-migrations", help="Skip automatic database migrations"),
):
    """Start an interactive chat session with teams' documents"""

    # Check if installation is complete
    _check_maru_app_installation()

    # Run migrations before starting chat
    if not skip_migrations:
        typer.echo("Checking for pending database migrations...")
        from maru_lang.core.relation_db.migration_utils import run_migrations_sync
        success = run_migrations_sync()
        if not success:
            typer.echo(
                "Migration check failed, but continuing to start chat...")
        typer.echo("")

    # Run with ORM context (required for document search)
    run_with_orm_context(chat_session, teams, max_turns)


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
        "[bold cyan]Maru Installer[/bold cyan]\n"
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
        help="Show detailed information (e.g., per-group statistics)"
    ),
):
    """Display the current status of the relational DB and vector DB."""
    run_with_orm_context(show_status, verbose)


@app.command()
def tree(
    name: Optional[str] = typer.Argument(
        None, help="DocumentGroup name (shows only root groups when omitted)"),
    depth: int = typer.Option(
        2, "--depth", "-d", help="Maximum depth to display (default: 2)"),
):
    """Show the DocumentGroup hierarchy."""
    run_with_orm_context(show_group_tree_command, name, depth)


@app.command()
def transfer(
    group_name: str = typer.Argument(...,
                                     help="DocumentGroup name to transfer"),
    new_manager_email: str = typer.Argument(...,
                                            help="Email of the new manager"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Transfer without confirmation"
    ),
):
    """Transfer DocumentGroup manager to another user"""
    run_with_orm_context(transfer_function, group_name,
                         new_manager_email, force)


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
        typer.echo("   maru install")
        typer.echo("")
        raise typer.Exit(1)

    return True
