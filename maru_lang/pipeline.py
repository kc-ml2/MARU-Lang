"""Minimal configuration for MARU's fixed indexing pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from maru_lang.enums import PipelineStage

PIPELINE_STAGES = tuple(PipelineStage)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """The two indexing options an agent may tune during the PoC."""

    target_tokens: int = 800
    overlap_tokens: int = 80

    def __post_init__(self) -> None:
        if not 200 <= self.target_tokens <= 2_000:
            raise ValueError("target_tokens must be between 200 and 2000")
        if not 0 <= self.overlap_tokens <= self.target_tokens // 4:
            raise ValueError("overlap_tokens must not exceed 25% of target_tokens")

    @classmethod
    def from_dict(cls, values: dict[str, object] | None) -> "PipelineConfig":
        return cls(**(values or {}))  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, int]:
        return asdict(self)
