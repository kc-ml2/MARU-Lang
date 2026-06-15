"""Parser routing for the ingest pipeline.

Decides which parser handles a file: the KorDoc MCP server or the LangChain
loaders.

Routing rules (only when kordoc_mcp_enabled):
    - KorDoc-only formats (hwp/hwpx/hwpml): always KorDoc.
    - Dual-support formats (pdf/docx/xls/xlsx): split by kordoc_mcp_ratio,
      decided deterministically from the document id so the same document always
      uses the same parser (stable across re-embeds, reproducible comparisons).
    - Everything else: the LangChain loaders.
"""
import asyncio
import hashlib
import logging
from pathlib import Path

from langchain_core.documents import Document

from maru_lang.configs import get_config
from maru_lang.constants import SUPPORTED_EXTENSIONS
from maru_lang.graph.ingest.constants import (
    KORDOC_DUAL_EXTENSIONS,
    KORDOC_ONLY_EXTENSIONS,
    PARSER_KORDOC,
    PARSER_LANGCHAIN,
)
from maru_lang.graph.ingest.loader import load_file
from maru_lang.graph.ingest.loader.kordoc_mcp import parse_with_kordoc

logger = logging.getLogger(__name__)


def ingestible_extensions() -> set[str]:
    """Formats this server can actually ingest under the current parser config.

    The static SUPPORTED_EXTENSIONS set includes KorDoc-only formats
    (hwp/hwpx/hwpml); when the KorDoc parser is disabled those would fail at
    parse time, so they're excluded here. GET /config serves this to clients
    so upload UIs offer only what will really work.
    """
    if get_config().kordoc_mcp_enabled:
        return set(SUPPORTED_EXTENSIONS)
    return set(SUPPORTED_EXTENSIONS) - KORDOC_ONLY_EXTENSIONS


def select_parser(ext: str, doc_id: str) -> str:
    """Return the parser id (PARSER_KORDOC / PARSER_LANGCHAIN) for a file.

    Args:
        ext: Lowercased file extension including the dot (e.g. ".pdf").
        doc_id: Document id, used as the stable key for the dual-format split.

    Raises:
        ValueError: For KorDoc-only formats (hwp/hwpx/hwpml) when KorDoc is
            disabled — no LangChain loader can read them.
    """
    cfg = get_config()
    if ext in KORDOC_ONLY_EXTENSIONS:
        if not cfg.kordoc_mcp_enabled:
            raise ValueError(
                f"{ext} files require the KorDoc parser; set kordoc_mcp_enabled=true."
            )
        logger.info("select_parser: %s (%s) -> kordoc (kordoc-only format)", ext, doc_id)
        return PARSER_KORDOC
    if not cfg.kordoc_mcp_enabled:
        logger.info("select_parser: %s (%s) -> langchain (kordoc disabled)", ext, doc_id)
        return PARSER_LANGCHAIN
    if ext in KORDOC_DUAL_EXTENSIONS:
        # Deterministic per-document split: hash(doc_id) -> [0, 100).
        bucket = int(hashlib.sha256(str(doc_id).encode()).hexdigest(), 16) % 100
        threshold = int(cfg.kordoc_mcp_ratio * 100)
        parser = PARSER_KORDOC if bucket < threshold else PARSER_LANGCHAIN
        logger.info(
            "select_parser: %s (%s) -> %s (dual; bucket=%d, ratio=%.2f, threshold=%d)",
            ext, doc_id, parser, bucket, cfg.kordoc_mcp_ratio, threshold,
        )
        return parser
    logger.info("select_parser: %s (%s) -> langchain (non-kordoc format)", ext, doc_id)
    return PARSER_LANGCHAIN


async def parse_file(file_path: Path, doc_id: str) -> tuple[list[Document], str]:
    """Parse a file with the selected parser.

    Returns:
        (documents, parser_id) where documents is a list of LangChain Documents.
    """
    ext = file_path.suffix.lower()
    parser = select_parser(ext, doc_id)
    logger.info("parse_file: parsing %s with %s", file_path.name, parser)

    if parser == PARSER_KORDOC:
        text = await parse_with_kordoc(file_path)
        docs = [Document(
            page_content=text,
            metadata={"source": str(file_path), "parser": PARSER_KORDOC},
        )]
    else:
        docs = await asyncio.to_thread(load_file, file_path)

    return docs, parser
