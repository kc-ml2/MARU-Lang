"""`maru test` — 대화형 integration 스모크 실행기.

provider를 고르고 (상황에 맞게) key/url/model을 입력받아, 임시 maru_config.yaml을
만들고 `pytest -m integration`(test_user_config_pipeline)을 알맞은 env로 실행한다.

보안: API 키는 가려서 입력받고(subprocess argv가 아니라) env로만 전달하며,
임시 config는 `${ENV:...}` 참조라 키를 디스크에 기록하지 않는다.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel

from maru_lang.constants import PROVIDER_GATE_ENV

console = Console()

# provider → 자주 쓰는 모델 후보 (첫 항목이 기본값). 목록에 없으면 직접 입력 가능.
_PROVIDER_MODELS = {
    "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
    "anthropic": ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"],
    "google": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
    "ollama": ["llama3.2", "qwen2.5", "gemma2", "mistral"],
    "vllm": [],  # 배포한 모델명을 직접 입력
}
_HOSTED = {"openai", "anthropic", "google"}        # API 키 필요
_SELF_HOSTED = {"ollama", "vllm"}                  # base_url 필요
_DEFAULT_BASE_URL = {"ollama": "http://localhost:11434", "vllm": ""}

# 스모크는 빠른 게 우선 — 경량 임베딩 기본값
_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _prompt_provider() -> str:
    providers = list(PROVIDER_GATE_ENV.keys())
    console.print("\n[bold]Provider 선택[/bold]")
    for i, p in enumerate(providers, 1):
        kind = "API 키" if p in _HOSTED else "base_url"
        console.print(f"  [cyan]{i}[/cyan]. {p} [dim]({kind})[/dim]")
    while True:
        raw = console.input("번호 입력 [1]: ").strip() or "1"
        if raw.isdigit() and 1 <= int(raw) <= len(providers):
            return providers[int(raw) - 1]
        console.print("[red]올바른 번호를 입력하세요.[/red]")


def _prompt_model(provider: str) -> str:
    """provider 모델 후보를 보여주고 번호 선택 또는 모델명 직접 입력을 받는다."""
    models = _PROVIDER_MODELS.get(provider, [])
    if not models:
        model = console.input("model (직접 입력): ").strip()
        if not model:
            console.print("[red]model이 필요합니다.[/red]")
            raise SystemExit(1)
        return model

    console.print("\n[bold]Model 선택[/bold] [dim](번호 선택 또는 모델명 직접 입력)[/dim]")
    for i, m in enumerate(models, 1):
        tag = " [dim](기본)[/dim]" if i == 1 else ""
        console.print(f"  [cyan]{i}[/cyan]. {m}{tag}")
    while True:
        raw = console.input("번호/모델명 [1]: ").strip()
        if not raw:
            return models[0]
        if raw.isdigit():
            idx = int(raw)
            if 1 <= idx <= len(models):
                return models[idx - 1]
            console.print("[red]범위 밖 번호입니다.[/red]")
            continue
        return raw  # 직접 입력한 모델명


def _build_config(provider: str, model: str, base_url: str | None) -> dict:
    """임시 maru_config.yaml 내용(dict) 생성."""
    llm: dict = {"name": provider, "provider": provider, "model_name": model}
    if provider in _HOSTED:
        # 키는 env로 전달 → config는 ${ENV:...} 참조 (디스크에 키 미기록)
        llm["api_key"] = f"${{ENV:{PROVIDER_GATE_ENV[provider]}}}"
    if base_url:
        llm["base_url"] = base_url
    return {
        "database_url": "sqlite://:memory:",
        "llms": [llm],
        "system_prompt": "You are MARU, an AI assistant. Answer in Korean.",
        "embedding_model": _EMBEDDING_MODEL,
        "retriever_top_k": 5,
        "retriever_search_method": "vector",
        "evaluate_method": "rule",
        "reranker_enabled": False,
    }


def _repo_root() -> Path:
    import maru_lang
    return Path(maru_lang.__file__).resolve().parent.parent


def run_test_command() -> None:
    """대화형으로 provider/키/모델을 받아 integration 스모크를 실행한다."""
    console.print(Panel.fit(
        "[bold cyan]MARU Integration Test[/bold cyan]\n"
        "선택한 provider로 전체 파이프라인(임베딩→검색→agent→RAG→응답)을 한 번 돌립니다.",
        border_style="cyan",
    ))

    repo_root = _repo_root()
    test_file = repo_root / "tests" / "configs" / "test_sample_config_e2e.py"
    if not test_file.exists():
        console.print(f"[red]테스트 파일을 찾을 수 없습니다: {test_file}[/red]")
        console.print("[dim]이 명령은 MARU 저장소 체크아웃에서 실행해야 합니다.[/dim]")
        raise SystemExit(1)

    provider = _prompt_provider()

    # 자격증명 (hosted=키 / self-hosted=base_url)
    api_key = None
    base_url = None
    if provider in _HOSTED:
        import typer
        api_key = typer.prompt(f"{provider} API key", hide_input=True).strip()
        if not api_key:
            console.print("[red]API 키가 비어 있습니다.[/red]")
            raise SystemExit(1)
    else:
        default_url = _DEFAULT_BASE_URL.get(provider, "")
        base_url = console.input(
            f"base_url" + (f" [{default_url}]" if default_url else "") + ": "
        ).strip() or default_url
        if not base_url:
            console.print("[red]base_url이 필요합니다.[/red]")
            raise SystemExit(1)

    # 모델 (목록 선택 또는 직접 입력)
    model = _prompt_model(provider)

    # 임시 config 디렉토리 구성
    tmp = tempfile.mkdtemp(prefix="maru-test-")
    try:
        app_dir = Path(tmp) / "maru_app"
        app_dir.mkdir()
        cfg = _build_config(provider, model, base_url)
        (app_dir / "maru_config.yaml").write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        # env 구성 — 키는 argv가 아니라 env로만 전달
        env = os.environ.copy()
        env["MARU_TEST_CONFIG_DIR"] = tmp
        if provider in _HOSTED:
            env[PROVIDER_GATE_ENV[provider]] = api_key

        console.print(
            f"\n[dim]provider={provider} model={model}"
            + (f" base_url={base_url}" if base_url else "")
            + f" embedding={_EMBEDDING_MODEL}[/dim]"
        )
        console.print("[cyan]integration 스모크 실행 중... (첫 실행 시 임베딩 다운로드)[/cyan]\n")

        cmd = [
            sys.executable, "-m", "pytest",
            str(test_file),
            "-m", "integration and llm_smoke", "-v", "-s",
        ]
        result = subprocess.run(cmd, cwd=str(repo_root), env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if result.returncode == 0:
        console.print("\n[bold green]✅ 통과 — 파이프라인이 정상 동작합니다.[/bold green]")
    else:
        console.print("\n[bold red]❌ 실패 — 위 pytest 출력을 확인하세요.[/bold red]")
        raise SystemExit(result.returncode)
