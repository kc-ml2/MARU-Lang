"""
Custom chunker template - Copy this file and remove .sample extension

This is a template for creating custom chunking strategies.
Implement the BaseChunker interface to add support for new chunking methods.
"""

from typing import List
from pathlib import Path
from maru_lang.pluggable.chunkers.base import BaseChunker
from maru_lang.models.ingest import ChunkInput


class CustomChunker(BaseChunker):
    """
    Template for custom chunking strategies.

    Copy this class to implement your own chunking method.
    """

    # Chunker identification
    name = "custom"
    description = "Custom chunking strategy"

    def __init__(self, max_chunk_size: int = 500):
        """
        Initialize the chunking strategy.

        Args:
            max_chunk_size: Maximum size of each chunk
        """
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str) -> List[ChunkInput]:
        """
        Split the text into chunks.

        Args:
            text: Complete text input

        Returns:
            List[ChunkInput]: Generated chunks
        """
        # Implement your chunking logic here.
        # Example: split by delimiter, semantic unit, etc.

        # Simple example: sentence-level splitting
        import re
        sentences = re.split(r'[.!?]+\s+', text)
        chunks = []

        for i, sentence in enumerate(sentences, start=1):
            if sentence.strip():
                chunks.append(ChunkInput(
                    number=i,
                    content=sentence.strip(),
                    meta={"chunk_method": "custom"}
                ))

        return chunks


# Example 1: Header-based chunking for Markdown
class HeaderBasedChunker(BaseChunker):
    """Chunk content based on Markdown headers."""

    name = "header"
    description = "Chunking by Markdown headers"

    def chunk(self, text: str) -> List[ChunkInput]:
        import re

        # Header pattern (lines beginning with # or ##)
        header_pattern = r'^(#{1,6})\s+(.+)$'

        chunks = []
        current_chunk = []
        current_header = "Introduction"
        chunk_num = 1

        for line in text.split('\n'):
            header_match = re.match(header_pattern, line, re.MULTILINE)

            if header_match:
                # Store the previous chunk
                if current_chunk:
                    chunks.append(ChunkInput(
                        number=chunk_num,
                        content='\n'.join(current_chunk),
                        meta={"header": current_header}
                    ))
                    chunk_num += 1

                # Start a new chunk
                current_header = header_match.group(2)
                current_chunk = [line]
            else:
                current_chunk.append(line)

        # Final chunk
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content='\n'.join(current_chunk),
                meta={"header": current_header}
            ))

        return chunks


# Example 2: Function-based chunking for Python code
class FunctionBasedChunker(BaseChunker):
    """Chunk Python code by function/class definitions."""

    name = "function"
    description = "Chunking by Python functions/classes"

    def chunk(self, text: str) -> List[ChunkInput]:
        import re

        # Pattern for detecting function/class definitions
        definition_pattern = r'^(def |class )'

        chunks = []
        current_chunk = []
        chunk_num = 1

        for line in text.split('\n'):
            # Detect a new function/class definition
            if re.match(definition_pattern, line) and current_chunk:
                # Store the previous chunk
                chunks.append(ChunkInput(
                    number=chunk_num,
                    content='\n'.join(current_chunk),
                ))
                chunk_num += 1
                current_chunk = []

            current_chunk.append(line)

        # Final chunk
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content='\n'.join(current_chunk),
            ))

        return chunks


# Example 3: Semantic chunking (sentence-embedding approach)
class SemanticChunker(BaseChunker):
    """Experimental semantic similarity-based chunker."""

    name = "semantic"
    description = "Semantic similarity chunking"

    def __init__(self, similarity_threshold: float = 0.7):
        """
        Args:
            similarity_threshold: Threshold for splitting chunks based on similarity
        """
        self.similarity_threshold = similarity_threshold

    def chunk(self, text: str) -> List[ChunkInput]:
        # This example is intentionally simple.
        # In production you would compute sentence embeddings and compare similarity.

        import re
        sentences = re.split(r'[.!?]+\s+', text)

        chunks = []
        current_chunk = []
        chunk_num = 1

        for sentence in sentences:
            if not sentence.strip():
                continue

            # In a real implementation, compute similarity with previous sentences here.
            # Start a new chunk when similarity falls below the threshold.

            if len(current_chunk) >= 5:  # Simple heuristic: split every 5 sentences
                chunks.append(ChunkInput(
                    number=chunk_num,
                    content=' '.join(current_chunk),
                    meta={"chunk_method": "semantic"}
                ))
                chunk_num += 1
                current_chunk = []

            current_chunk.append(sentence.strip())

        # Final chunk
        if current_chunk:
            chunks.append(ChunkInput(
                number=chunk_num,
                content=' '.join(current_chunk),
                meta={"chunk_method": "semantic"}
            ))

        return chunks
