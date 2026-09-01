"""Stable indexing pipeline configuration shared by services and transports."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from maru_lang.enums import PipelineStage

PIPELINE_STAGES = tuple(PipelineStage)
SUPPORTED_PARSERS = frozenset({"auto", "markdown", "text"})
SUPPORTED_CHUNKERS = frozenset({"structure"})


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Validated settings for MARU's fixed indexing pipeline."""

    parser: str = "auto"
    chunker: str = "structure"
    target_tokens: int = 800
    overlap_tokens: int = 80
    embedding_model: str = "multilingual-default"

    def __post_init__(self) -> None:
        if self.parser not in SUPPORTED_PARSERS:
            raise ValueError(f"Unsupported parser: {self.parser}")
        if self.chunker not in SUPPORTED_CHUNKERS:
            raise ValueError(f"Unsupported chunker: {self.chunker}")
        if not 200 <= self.target_tokens <= 2_000:
            raise ValueError("target_tokens must be between 200 and 2000")
        if not 0 <= self.overlap_tokens <= self.target_tokens // 4:
            raise ValueError("overlap_tokens must not exceed 25% of target_tokens")
        if not self.embedding_model.strip():
            raise ValueError("embedding_model must not be empty")

    @classmethod
    def from_dict(cls, values: dict[str, object] | None) -> "PipelineConfig":
        return cls(**(values or {}))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()
