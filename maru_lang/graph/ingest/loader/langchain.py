"""LangChain-based document loader - format-specific file loading."""
import platform
from pathlib import Path

from langchain_core.documents import Document

from maru_lang.constants import SUPPORTED_EXTENSIONS

# doc2txt (antiword backend) only supports these platform triples.
# On unsupported platforms (e.g. Linux ARM64, macOS Intel), RuntimeError is
# raised — never fall back to TextLoader for binary .doc files.
_DOC2TXT_SUPPORTED = (
    ("Darwin", "arm64"),   # macOS Apple Silicon
    ("Linux", "x86_64"),   # Linux AMD64
    ("Windows", "AMD64"),  # Windows AMD64
)


def _doc2txt_available() -> bool:
    """Return True when the current platform is supported by doc2txt/antiword."""
    return (platform.system(), platform.machine()) in _DOC2TXT_SUPPORTED


def load_file(file_path: Path) -> list[Document]:
    """Load a file into LangChain Documents.

    Supported formats: PDF, DOCX, PPTX, XLSX, CSV, HTML, JSON, Markdown, TXT, etc.
    """
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        from langchain_community.document_loaders import UnstructuredPDFLoader
        return UnstructuredPDFLoader(str(file_path)).load()

    elif suffix == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(str(file_path)).load()

    elif suffix == ".doc":
        # Docx2txtLoader does NOT support .doc (OLE2 binary format).
        # Use doc2txt (wraps antiword) on supported platforms only.
        if _doc2txt_available():
            import doc2txt
            text = doc2txt.extract_text(str(file_path))
            return [Document(page_content=text, metadata={"source": str(file_path)})]
        # Unsupported platform — do NOT fall back to TextLoader. Ingesting a
        # binary OLE2 file as raw text would produce garbage embeddings and
        # could corrupt the vector store. Raise so the caller can surface a
        # clear message (e.g. "DOC files are not supported on this platform").
        raise RuntimeError(
            f".doc files require a supported platform (macOS Apple Silicon, "
            f"Linux x86_64, or Windows AMD64). Current platform: "
            f"{platform.system()} {platform.machine()}. "
            f"Please move the file to a supported host or convert to .docx first."
        )

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
    """Check if the file format is supported for ingestion.

    Platform-aware: .doc files are only supported on platforms where
    doc2txt/antiword is available (macOS Apple Silicon, Linux x86_64,
    Windows AMD64). On unsupported platforms this returns False so the
    UI never offers a .doc file that will fail at ingest time.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".doc" and not _doc2txt_available():
        return False
    return suffix in SUPPORTED_EXTENSIONS
