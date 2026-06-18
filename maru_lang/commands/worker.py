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


def worker_env(cwd: str, gpu: str | None = None) -> dict:
    """Env for the worker subprocess: put cwd on PYTHONPATH so imports resolve
    the same way `maru run`'s server launch does.

    When gpu is given, pin the worker to that single GPU via CUDA_VISIBLE_DEVICES
    (gpu is a CUDA_VISIBLE_DEVICES token — an index or UUID, see plan_worker_gpus).
    Only that GPU is visible inside the process, so a plain "cuda" device resolves
    to it (as cuda:0 in the process's own view).
    """
    env = os.environ.copy()
    paths = [cwd]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    return env


def _worker_cmd() -> list:
    return [sys.executable, "-m", "arq", WORKER_SETTINGS_PATH]


def spawn_worker(cwd: str | None = None, gpu: str | None = None) -> subprocess.Popen:
    """Launch one ARQ ingest worker as a background subprocess.

    gpu pins the worker to one GPU (see worker_env); None lets the worker use
    the configured/auto device unchanged.
    """
    cwd = cwd or os.getcwd()
    return subprocess.Popen(_worker_cmd(), cwd=cwd, env=worker_env(cwd, gpu))


def _detect_cuda_count() -> int:
    """Number of CUDA GPUs visible to torch (0 if torch/CUDA unavailable)."""
    try:
        import torch
        return torch.cuda.device_count()
    except Exception:
        return 0


def _visible_gpu_tokens() -> list[str]:
    """GPUs available to distribute across, as CUDA_VISIBLE_DEVICES tokens.

    If CUDA_VISIBLE_DEVICES is already set (e.g. an ops-set isolation mask like
    "2,3"), distribute over *those* tokens so we never punch through the mask
    onto other physical GPUs. Only when no mask is set do we fall back to torch's
    own device indices 0..N-1.
    """
    masked = os.environ.get("CUDA_VISIBLE_DEVICES")
    if masked is not None and masked.strip() != "":
        return [tok.strip() for tok in masked.split(",") if tok.strip()]
    return [str(i) for i in range(_detect_cuda_count())]


def plan_worker_gpus(count: int, resolved_device: str | None) -> list[str | None]:
    """Round-robin GPU tokens for `count` workers spawned together.

    Returns a per-worker list of CUDA_VISIBLE_DEVICES tokens to pin, or None
    entries when auto-assignment should not apply:
      - device explicitly pinned (e.g. "cuda:1") or non-CUDA ("cpu"/"mps") -> hands off
      - device is None (auto) or bare "cuda" -> distribute across visible GPUs
    Respects an existing CUDA_VISIBLE_DEVICES mask (distributes within it, so we
    don't break ops-level GPU isolation). Falls back to all-None when 0 or 1 GPU
    is visible (nothing to distribute).
    """
    if resolved_device is not None and resolved_device.strip().lower() != "cuda":
        # "cuda:0", "cpu", "mps", ... -> respect the user's choice as-is.
        return [None] * count
    tokens = _visible_gpu_tokens()
    if len(tokens) <= 1:
        return [None] * count
    return [tokens[i % len(tokens)] for i in range(count)]


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
