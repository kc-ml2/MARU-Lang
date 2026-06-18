"""Multi-GPU worker assignment: round-robin pinning + env injection."""
import maru_lang.commands.worker as worker_mod
from maru_lang.commands.worker import plan_worker_gpus, worker_env


def _patch_gpus(monkeypatch, n):
    """Pretend torch sees `n` GPUs and no CUDA_VISIBLE_DEVICES mask is set."""
    monkeypatch.setattr(worker_mod, "_detect_cuda_count", lambda: n)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)


def test_round_robin_across_two_gpus(monkeypatch):
    # 2 GPUs, 2 workers -> one per GPU (the reported bug: both landed on GPU 0).
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, None) == ["0", "1"]
    assert plan_worker_gpus(2, "cuda") == ["0", "1"]


def test_round_robin_wraps_when_more_workers_than_gpus(monkeypatch):
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(3, None) == ["0", "1", "0"]


def test_no_assignment_with_single_or_no_gpu(monkeypatch):
    _patch_gpus(monkeypatch, 1)
    assert plan_worker_gpus(2, "cuda") == [None, None]
    _patch_gpus(monkeypatch, 0)
    assert plan_worker_gpus(2, None) == [None, None]


def test_explicit_device_index_is_respected(monkeypatch):
    # User pinned a specific GPU -> hands off, even with multiple GPUs present.
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, "cuda:1") == [None, None]


def test_non_cuda_device_is_left_alone(monkeypatch):
    _patch_gpus(monkeypatch, 2)
    assert plan_worker_gpus(2, "cpu") == [None, None]
    assert plan_worker_gpus(2, "mps") == [None, None]


def test_respects_existing_cuda_visible_devices_mask(monkeypatch):
    # Ops pinned the process to physical GPUs 2,3. We must distribute over THOSE
    # tokens, never punch through to physical 0/1 (would break GPU isolation).
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")
    # torch sees 2 GPUs (the masked ones); device_count must NOT override the mask.
    monkeypatch.setattr(worker_mod, "_detect_cuda_count", lambda: 2)
    assert plan_worker_gpus(2, "cuda") == ["2", "3"]
    assert plan_worker_gpus(3, None) == ["2", "3", "2"]


def test_mask_with_single_device_yields_no_assignment(monkeypatch):
    # Mask exposes one GPU -> nothing to distribute, leave workers alone.
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    assert plan_worker_gpus(2, "cuda") == [None, None]


def test_mask_tokens_can_be_uuids(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-aaa, GPU-bbb")
    assert plan_worker_gpus(2, None) == ["GPU-aaa", "GPU-bbb"]


def test_worker_env_sets_cuda_visible_devices(tmp_path):
    env = worker_env(str(tmp_path), gpu="1")
    assert env["CUDA_VISIBLE_DEVICES"] == "1"


def test_worker_env_omits_cuda_visible_devices_when_unpinned(tmp_path, monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    env = worker_env(str(tmp_path))
    assert "CUDA_VISIBLE_DEVICES" not in env
