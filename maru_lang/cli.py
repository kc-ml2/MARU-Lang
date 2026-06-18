from maru_lang.commands.status import show_status
from maru_lang.commands.install import install_configs
from maru_lang.commands.run import run_session
from maru_lang.commands.test import run_test_command
from maru_lang.core.relation_db.connection import run_with_orm_context
from maru_lang.constants import PUBLIC_TEAM_NAME
import asyncio
import logging
import sys
import os
import typer
import uvicorn
import subprocess
from pathlib import Path
from typing import Optional
from maru_lang.configs import get_config

app = typer.Typer()


def _enable_verbose_logging() -> None:
    """Turn on DEBUG logs for maru_lang.* (quiet by default)."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("maru_lang").setLevel(logging.DEBUG)


@app.callback()
def common_init(ctx: typer.Context):
    """Common initialization before all commands"""
    # Skip for commands that don't need the project config loaded.
    # (install: not set up yet; test: uses its own temp config)
    if ctx.invoked_subcommand in ("install", "test"):
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
    worker: int = typer.Option(
        0, "--worker",
        help="Number of ARQ ingest workers to co-launch (0=none; distinct from --workers, "
             "which sets uvicorn server workers; needs task_queue_enabled)"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable DEBUG logs for maru_lang (default: quiet)"),
):
    """Start the chatbot FastAPI server (default: maru_app/main.py)"""

    if verbose:
        _enable_verbose_logging()

    config = get_config()
    _require_queue_for_worker(config, worker)

    # Check if installation is complete
    _check_maru_app_installation()

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

    # Optionally co-launch ARQ ingest worker(s); torn down when the server exits.
    worker_procs = _start_ingest_workers(config, worker)

    try:
        if workers > 1:
            # Execute uvicorn CLI in a subprocess for multi-worker mode
            typer.echo("🔧 Production mode: running with multiple workers")

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
    finally:
        for p in worker_procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if worker_procs:
            typer.echo(f"✓ Ingest worker(s) stopped ({len(worker_procs)})")


def _require_queue_for_worker(config, worker_count: int) -> None:
    """Fail fast when --worker is requested but the task queue is off.

    A worker without task_queue_enabled+redis_url can never receive jobs, so
    treat it as a misconfiguration and refuse to start (rather than warn+skip).
    """
    if worker_count > 0 and not config.queue_enabled:
        typer.echo(
            "❌ --worker requires task_queue_enabled: true and redis_url in maru_config.yaml.\n"
            "   Enable the queue, or drop --worker to run ingest in-process."
        )
        raise typer.Exit(1)


def _start_ingest_workers(config, count: int) -> list:
    """Launch `count` ARQ ingest worker subprocesses (empty list if count<=0)."""
    if count <= 0:
        return []
    from maru_lang.commands.worker import plan_worker_gpus, spawn_worker
    gpus = plan_worker_gpus(count, config.resolve_ingest_embedding_device())
    pinned = [g for g in gpus if g is not None]
    suffix = f", gpus={','.join(pinned)}" if pinned else ""
    typer.echo(f"🧵 Starting {count} ingest worker(s) (redis={config.redis_url}{suffix})")
    return [spawn_worker(gpu=g) for g in gpus]


@app.command()
def run(
    teams: str = typer.Option(None, "--team", "-t",
                              help="Team names (comma-separated). Default: 'public' (switch in chat with /team)."),
    host: str = typer.Option(None, help="Server host"),
    port: int = typer.Option(None, help="Server port"),
    worker: int = typer.Option(
        0, "--worker",
        help="Number of ARQ ingest workers to co-launch (0=none; needs task_queue_enabled)"),
    attach: bool = typer.Option(
        False, "--attach", "-a",
        help="Attach the chat REPL to an already-running maru server (e.g. a "
             "systemd `maru serve`) instead of starting one"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable DEBUG logs for maru_lang (default: quiet)"),
):
    """Start server + interactive chat in one command."""
    if verbose:
        _enable_verbose_logging()

    if attach and worker:
        typer.echo("❌ --attach cannot be combined with --worker: the running "
                   "server (service) owns its workers.")
        raise typer.Exit(1)

    if not teams:
        # No --team given: start on the default 'public' team without blocking
        # on a prompt. Switch any time in chat with /team <name>.
        teams = PUBLIC_TEAM_NAME
        typer.echo(
            f"ℹ️  No --team given; starting on '{PUBLIC_TEAM_NAME}' "
            "(switch in chat with /team <name>)."
        )

    _check_maru_app_installation()

    config = get_config()
    _require_queue_for_worker(config, worker)
    host = host or config.server.host
    port = port or config.server.port

    team_list = [t.strip() for t in teams.split(",") if t.strip()]

    asyncio.run(run_session(
        team_names=team_list,
        host=host,
        port=port,
        worker_count=worker,
        attach=attach,
    ))


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


@app.command("test")
def test_command():
    """Run an interactive integration smoke test (pick provider, key/url, model)."""
    run_test_command()


@app.command("worker")
def worker_command():
    """Run the ARQ ingest worker (requires task_queue_enabled + redis_url)."""
    from maru_lang.commands.worker import run_worker_command
    raise typer.Exit(run_worker_command())



def _check_maru_app_installation() -> bool:
    """Check if required files exist and guide user to install if not."""
    maru_app_path = Path.cwd() / "maru_app"

    missing_items = []

    if not maru_app_path.exists():
        missing_items.append("maru_app/ directory")
    else:
        if not (maru_app_path / "main.py").exists():
            missing_items.append("maru_app/main.py")
        if not (maru_app_path / "maru_config.yaml").exists():
            missing_items.append("maru_app/maru_config.yaml")

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
