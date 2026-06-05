"""worker command — run the ARQ ingest worker as a separate process."""
import os
import subprocess
import sys

from rich.console import Console

from maru_lang.configs import get_config

console = Console()


def run_worker_command() -> int:
    """Launch `arq maru_lang.worker.WorkerSettings` in the project context.

    Requires task_queue_enabled + redis_url in maru_config.yaml. Run this
    alongside `maru serve`/`maru run` (one machine, separate process).
    """
    cfg = get_config()
    if not cfg.task_queue_enabled or not cfg.redis_url:
        console.print(
            "[red]Task queue is not enabled.[/red] "
            "Set [bold]task_queue_enabled: true[/bold] and [bold]redis_url[/bold] "
            "in maru_config.yaml to run the worker."
        )
        return 1

    cwd = os.getcwd()
    env = os.environ.copy()
    # Mirror `maru run`'s server launch so worker imports + relative paths resolve.
    paths = [cwd]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)

    console.print(
        f"[green]Starting ARQ ingest worker[/green] (redis={cfg.redis_url}, "
        f"model={cfg.embedding_model}, device={cfg.embedding_device or 'auto'})"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "arq", "maru_lang.worker.WorkerSettings"],
        cwd=cwd,
        env=env,
    )
    return proc.returncode
