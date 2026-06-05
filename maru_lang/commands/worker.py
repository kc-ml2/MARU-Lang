"""worker command + shared helpers for launching the ARQ ingest worker.

Single source of truth for spawning the worker, reused by `maru worker`
(foreground) and the `--worker N` co-launch in `maru run`/`maru serve`
(background subprocesses).
"""
import os
import subprocess
import sys

from rich.console import Console

from maru_lang.configs import get_config

console = Console()

# ARQ worker entrypoint, referenced in one place only.
WORKER_SETTINGS_PATH = "maru_lang.worker.WorkerSettings"


def worker_env(cwd: str) -> dict:
    """Env for the worker subprocess: put cwd on PYTHONPATH so imports resolve
    the same way `maru run`'s server launch does."""
    env = os.environ.copy()
    paths = [cwd]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _worker_cmd() -> list:
    return [sys.executable, "-m", "arq", WORKER_SETTINGS_PATH]


def spawn_worker(cwd: str | None = None) -> subprocess.Popen:
    """Launch one ARQ ingest worker as a background subprocess."""
    cwd = cwd or os.getcwd()
    return subprocess.Popen(_worker_cmd(), cwd=cwd, env=worker_env(cwd))


def run_worker_command() -> int:
    """Run the ARQ ingest worker in the foreground (the `maru worker` command).

    Requires task_queue_enabled + redis_url in maru_config.yaml. Run this
    alongside `maru serve`/`maru run` (one machine, separate process).
    """
    cfg = get_config()
    if not cfg.queue_enabled:
        console.print(
            "[red]Task queue is not enabled.[/red] "
            "Set [bold]task_queue_enabled: true[/bold] and [bold]redis_url[/bold] "
            "in maru_config.yaml to run the worker."
        )
        return 1

    cwd = os.getcwd()
    console.print(
        f"[green]Starting ARQ ingest worker[/green] (redis={cfg.redis_url}, "
        f"model={cfg.embedding_model}, device={cfg.resolve_ingest_embedding_device() or 'auto'})"
    )
    proc = subprocess.run(_worker_cmd(), cwd=cwd, env=worker_env(cwd))
    return proc.returncode
