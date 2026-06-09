"""Constants cohesive to the ingest graph.

Vocabulary used across the ingest pipeline's own modules (parser routing,
KorDoc-supported formats). App-wide constants — what files may be uploaded
(SUPPORTED_EXTENSIONS), the ARQ task name shared with the API — live in
maru_lang.constants instead; these stay here because nothing outside the ingest
graph needs them.
"""

# Parser identifiers recorded in Document.metadata["parser"] (a stored contract,
# so the string values are stable) and used to route in parser.py.
PARSER_KORDOC = "kordoc"
PARSER_LANGCHAIN = "langchain"

# Formats the KorDoc MCP server (`parse_document` tool) can parse to Markdown.
KORDOC_EXTENSIONS = {
    ".hwp", ".hwpx", ".hwpml", ".pdf", ".xls", ".xlsx", ".docx",
}
# KorDoc-only formats: no LangChain loader exists, so these always go to KorDoc
# (and can only be ingested when kordoc_mcp_enabled).
KORDOC_ONLY_EXTENSIONS = {".hwp", ".hwpx", ".hwpml"}
# Formats both KorDoc and the LangChain loaders can parse. When KorDoc is
# enabled these are split between the two parsers by kordoc_mcp_ratio so the
# parsing quality of each can be compared on the same corpus.
KORDOC_DUAL_EXTENSIONS = KORDOC_EXTENSIONS - KORDOC_ONLY_EXTENSIONS
