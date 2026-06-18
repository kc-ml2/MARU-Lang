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


def worker_env(cwd: str, gpu_id: int | None = None) -> dict:
    """Env for the worker subprocess: put cwd on PYTHONPATH so imports resolve
    the same way `maru run`'s server launch does.

    When gpu_id is given, pin the worker to that single physical GPU via
    CUDA_VISIBLE_DEVICES. Only that GPU is visible inside the process, so a
    plain "cuda" device resolves to it (as cuda:0 in the process's own view).
    """
    env = os.environ.copy()
    paths = [cwd]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    if gpu_id is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    return env


def _worker_cmd() -> list:
    return [sys.executable, "-m", "arq", WORKER_SETTINGS_PATH]


def spawn_worker(cwd: str | None = None, gpu_id: int | None = None) -> subprocess.Popen:
    """Launch one ARQ ingest worker as a background subprocess.

    gpu_id pins the worker to one physical GPU (see worker_env); None lets the
    worker use the configured/auto device unchanged.
    """
    cwd = cwd or os.getcwd()
    return subprocess.Popen(_worker_cmd(), cwd=cwd, env=worker_env(cwd, gpu_id))


def _detect_cuda_count() -> int:
    """Number of CUDA GPUs visible to torch (0 if torch/CUDA unavailable)."""
    try:
        import torch
        return torch.cuda.device_count()
    except Exception:
        return 0


def plan_worker_gpus(count: int, resolved_device: str | None) -> list[int | None]:
    """Round-robin GPU ids for `count` workers spawned together.

    Returns a per-worker list of physical GPU ids to pin (via CUDA_VISIBLE_DEVICES),
    or None entries when auto-assignment should not apply:
      - device explicitly pinned (e.g. "cuda:1") or non-CUDA ("cpu"/"mps") -> hands off
      - device is None (auto) or bare "cuda" -> distribute across detected GPUs
    Falls back to all-None when 0 or 1 GPU is detected (nothing to distribute).
    """
    if resolved_device is not None and resolved_device.strip().lower() != "cuda":
        # "cuda:0", "cpu", "mps", ... -> respect the user's choice as-is.
        return [None] * count
    n = _detect_cuda_count()
    if n <= 1:
        return [None] * count
    return [i % n for i in range(count)]


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
