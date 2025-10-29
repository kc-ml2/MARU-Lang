"""
Custom parser template - Copy this file and remove .sample extension

This is a template for creating custom document parsers.
Implement the BaseParser interface to add support for new file formats.
"""

from pathlib import Path
from maru_lang.pluggable.loaders.base import BaseParser, ParseResult


class CustomParser(BaseParser):
    """
    Template for custom file parsers.

    Copy this class to implement support for new file formats.
    """

    def parse(self, file_path: Path) -> ParseResult:
        """
        Parse the file and extract textual content.

        Args:
            file_path: Path to the file to parse

        Returns:
            ParseResult: Parsed text and metadata

        Raises:
            ValueError: Raised when parsing fails or content cannot be read
            FileNotFoundError: Raised when the file does not exist
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            # Implement your parsing logic here
            # Example: convert JSON, XML, or CSV into plain text

            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Optional metadata enrichment
            metadata = {
                'file_type': 'custom',
                'file_size': file_path.stat().st_size,
                # Add additional metadata as needed
            }

            return ParseResult(content=content, metadata=metadata)

        except Exception as e:
            raise ValueError(f"Failed to parse file: {file_path}") from e

    def supports(self, file_path: Path) -> bool:
        """
        Determine whether this parser supports the given file.

        Args:
            file_path: Path of the file to check

        Returns:
            bool: True if the file is supported, otherwise False
        """
        return file_path.suffix.lower() in self.supported_extensions

    @property
    def supported_extensions(self) -> list[str]:
        """
        List of file extensions supported by this parser

        Returns:
            list[str]: Supported extensions (e.g., ['.json', '.jsonl'])
        """
        # Update this list with the extensions you support
        return ['.custom', '.cst']


# Example: JSON parser
class JsonParser(BaseParser):
    """Example parser for JSON files"""

    def parse(self, file_path: Path) -> ParseResult:
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            import json

            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Convert JSON into formatted text
            content = json.dumps(data, indent=2, ensure_ascii=False)

            metadata = {
                'file_type': 'json',
                'file_size': file_path.stat().st_size,
            }

            return ParseResult(content=content, metadata=metadata)

        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse error: {file_path}") from e
        except Exception as e:
            raise ValueError(f"Failed to read file: {file_path}") from e
