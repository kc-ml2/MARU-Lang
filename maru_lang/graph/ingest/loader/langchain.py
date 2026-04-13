"""LangChain-based document loader - format-specific file loading."""
from pathlib import Path

from langchain_core.documents import Document

from maru_lang.constants import SUPPORTED_EXTENSIONS


def load_file(file_path: Path) -> list[Document]:
    """Load a file into LangChain Documents.

    Supported formats: PDF, DOCX, PPTX, XLSX, CSV, HTML, JSON, Markdown, TXT, etc.
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        from langchain_community.document_loaders import UnstructuredPDFLoader
        return UnstructuredPDFLoader(str(file_path)).load()

    elif suffix in (".docx", ".doc"):
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(str(file_path)).load()

    elif suffix == ".pptx":
        from langchain_community.document_loaders import UnstructuredPowerPointLoader
        return UnstructuredPowerPointLoader(str(file_path)).load()

    elif suffix in (".xlsx", ".xls"):
        from langchain_community.document_loaders import UnstructuredExcelLoader
        return UnstructuredExcelLoader(str(file_path)).load()

    elif suffix in (".csv", ".tsv"):
        from langchain_community.document_loaders import CSVLoader
        return CSVLoader(str(file_path)).load()

    elif suffix in (".html", ".htm"):
        from langchain_community.document_loaders import BSHTMLLoader
        return BSHTMLLoader(str(file_path)).load()

    elif suffix == ".json":
        from langchain_community.document_loaders import JSONLoader
        return JSONLoader(
            file_path=str(file_path),
            jq_schema=".",
            text_content=False,
        ).load()

    elif suffix in (".md", ".markdown", ".yaml", ".yml", ".xml"):
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()

    else:
        # Default: load as plain text (txt, log, py, js, ts, etc.)
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()


def is_supported(file_path: Path) -> bool:
    """Check if the file format is supported for ingestion."""
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS
