"""Prepare ingest sources as readable local files before upload or parsing."""

from maru_lang.graph.ingest.materialization.base import (
    Materialization,
    MaterializationResolver,
    materialize_file,
)

__all__ = ["Materialization", "MaterializationResolver", "materialize_file"]
