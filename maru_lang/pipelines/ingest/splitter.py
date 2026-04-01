"""LangChain 기반 Text Splitter - 텍스트 분할 전략"""
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def create_splitter(
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> RecursiveCharacterTextSplitter:
    """RecursiveCharacterTextSplitter 생성.

    한국어/영어 혼합 텍스트에 최적화된 separators 사용.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n\n",     # 문단
            "\n",       # 줄바꿈
            "。",       # 일본어/중국어 마침표 (가끔 한국어 문서에도)
            ". ",       # 영어 문장
            "? ",
            "! ",
            ".\n",
            " ",        # 단어
            "",         # 최후 수단: 글자 단위
        ],
        length_function=len,
    )


def split_documents(
    documents: list[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[Document]:
    """Document 리스트를 청크로 분할."""
    splitter = create_splitter(chunk_size, chunk_overlap)
    return splitter.split_documents(documents)
