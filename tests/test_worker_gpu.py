"""Multi-GPU worker assignment: round-robin pinning + env injection.

Workers are co-launched next to the main `maru serve` process, which also loads
an embedding model (on config.embedding_device, GPU 0 under auto). So the worker
round-robin starts *after* the main process's GPU — with 2 GPUs a single worker
lands on GPU 1, leaving GPU 0 for the server.
"""
import maru_lang.commands.worker as worker_mod
from maru_lang.commands.worker import plan_worker_gpus, worker_env


def _patch_gpus(monkeypatch, n):
    """Pretend torch sees `n` GPUs and no CUDA_VISIBLE_DEVICES mask is set."""
    monkeypatch.setattr(worker_mod, "_detect_cuda_count", lambda: n)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def test_single_worker_avoids_main_gpu(monkeypatch):
    # The reported case: `maru serve --worker 1` on a 2-GPU box put the server's
    # and the worker's embedding model both on GPU 0. The worker must take GPU 1.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(1, None) == ["1"]
    assert plan_worker_gpus(1, "cuda") == ["1"]


def test_two_workers_start_after_main_gpu(monkeypatch):
    # 2 GPUs, 2 workers: first worker takes the free GPU 1; the second wraps back
    # onto GPU 0 (shared with the server) so no GPU sits idle.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, None) == ["1", "0"]


def test_offset_round_robin_four_gpus(monkeypatch):
    _patch_gpus(monkeypatch, 4)
    assert plan_worker_gpus(1, None) == ["1"]
    assert plan_worker_gpus(3, None) == ["1", "2", "3"]      # GPU 0 (main) untouched
    assert plan_worker_gpus(4, None) == ["1", "2", "3", "0"]  # wraps onto main last


def test_main_on_cpu_frees_gpu_zero(monkeypatch):
    # Server embeds on CPU -> GPU 0 is free, so workers may start at 0.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, None, main_device="cpu") == ["0", "1"]
    assert plan_worker_gpus(1, "cuda", main_device="mps") == ["0"]


def test_main_pinned_to_gpu_one_is_reserved(monkeypatch):
    # Server pinned to GPU 1 -> workers avoid GPU 1, starting at GPU 0.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(1, "cuda", main_device="cuda:1") == ["0"]
    assert plan_worker_gpus(2, None, main_device="cuda:1") == ["0", "1"]


def test_no_assignment_with_single_or_no_gpu(monkeypatch):
    _patch_gpus(monkeypatch, 1)
    assert plan_worker_gpus(2, "cuda") == [None, None]
    _patch_gpus(monkeypatch, 0)
    assert plan_worker_gpus(2, None) == [None, None]


def test_explicit_ingest_device_index_is_respected(monkeypatch):
    # Ingest device pinned to a specific GPU -> hands off, even with multiple GPUs.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, "cuda:1") == [None, None]


def test_non_cuda_ingest_device_is_left_alone(monkeypatch):
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, "cpu") == [None, None]
    assert plan_worker_gpus(2, "mps") == [None, None]


def test_respects_existing_cuda_visible_devices_mask(monkeypatch):
    # Ops pinned the process to physical GPUs 2,3. We distribute over THOSE tokens,
    # never punching through to physical 0/1. The main server (auto) takes the first
    # visible one (token "2"), so workers start at "3".
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")
    monkeypatch.setattr(worker_mod, "_detect_cuda_count", lambda: 2)
    assert plan_worker_gpus(1, "cuda") == ["3"]
    assert plan_worker_gpus(3, None) == ["3", "2", "3"]


def test_mask_with_single_device_yields_no_assignment(monkeypatch):
    # Mask exposes one GPU -> nothing to distribute, leave workers alone.
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    assert plan_worker_gpus(2, "cuda") == [None, None]


def test_mask_tokens_can_be_uuids(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-aaa, GPU-bbb")
    # main auto -> takes GPU-aaa; the worker starts after it, on GPU-bbb.
    assert plan_worker_gpus(1, None) == ["GPU-bbb"]
    assert plan_worker_gpus(2, None) == ["GPU-bbb", "GPU-aaa"]


def test_worker_env_sets_cuda_visible_devices(tmp_path):
    env = worker_env(str(tmp_path), gpu="1")
    assert env["CUDA_VISIBLE_DEVICES"] == "1"


def test_worker_env_omits_cuda_visible_devices_when_unpinned(tmp_path, monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    env = worker_env(str(tmp_path))
    assert "CUDA_VISIBLE_DEVICES" not in env
