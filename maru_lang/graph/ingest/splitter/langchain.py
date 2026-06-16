"""LangChain-based text splitter - chunking strategies."""
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def create_splitter(
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> RecursiveCharacterTextSplitter:
    """Create a RecursiveCharacterTextSplitter optimized for Korean/English mixed text."""
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n\n",     # Paragraph
            "\n",       # Line break
            "\u3002",   # CJK period (occasionally in Korean docs)
            ". ",       # English sentence
            "? ",
            "! ",
            ".\n",
            " ",        # Word
            "",         # Last resort: character-level
        ],
        length_function=len,
    )


def split_documents(
    documents: list[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[Document]:
    """Split a list of Documents into chunks."""
    splitter = create_splitter(chunk_size, chunk_overlap)
    return splitter.split_documents(documents)
