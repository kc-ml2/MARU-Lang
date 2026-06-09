"""Exceptions raised by the ingest graph.

A small domain hierarchy so callers can catch ingest failures by category
(`except IngestError`) without depending on the specific parser module that
raised them.
"""


class IngestError(RuntimeError):
    """Base class for ingest-pipeline failures."""


class KordocParseError(IngestError):
    """The KorDoc MCP server failed to parse a document (error, transport, or timeout)."""
