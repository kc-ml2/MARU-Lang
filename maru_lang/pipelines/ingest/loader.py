"""LangChain 기반 Document Loader - 파일 포맷별 로딩"""
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document

from maru_lang.constants import SUPPORTED_EXTENSIONS
def load_file(file_path: Path) -> list[Document]:
    """파일을 LangChain Document로 로드.

    지원 포맷: PDF, DOCX, PPTX, XLSX, CSV, HTML, JSON, Markdown, TXT 등
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        return PyPDFLoader(str(file_path)).load()

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

    elif suffix in (".md", ".markdown"):
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()

    elif suffix in (".yaml", ".yml"):
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()

    elif suffix == ".xml":
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()

    else:
        # 기본: 텍스트로 로드 (txt, log, py, js, ts 등)
        from langchain_community.document_loaders import TextLoader
        return TextLoader(str(file_path), encoding="utf-8").load()


def is_supported(file_path: Path) -> bool:
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS
