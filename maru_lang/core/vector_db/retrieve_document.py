from typing import Any, Optional, TYPE_CHECKING
from datetime import datetime
from pydantic import BaseModel, Field, computed_field

if TYPE_CHECKING:
    from maru_lang.schemas.chat import DocumentReference


class RetrieveDocument(BaseModel):
    id: str
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def source(self) -> str:
        return self.metadata.get("document_name", "알 수 없는 소스")

    @computed_field
    @property
    def code(self) -> str:
        return self.metadata.get("document_code", "unknown")

    @computed_field
    @property
    def page(self) -> int:
        return self.metadata.get("number", 1)

    def __repr__(self):
        preview = self.page_content[:60].replace("\n", " ")
        if len(self.page_content) > 60:
            preview += "..."
        return f"RetrieveDocument(id='{self.id}', page_content='{preview}', metadata={self.metadata})"

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_clean_dict(self) -> dict:
        """
        Return a cleaned version without page_content (for API responses).
        Only includes metadata and computed fields like source, code, page.
        """
        return {
            "id": self.id,
            "source": self.source,
            "code": self.code,
            "page": self.page,
            "metadata": self.metadata
        }

    def to_document_reference(self) -> 'DocumentReference':
        """
        Convert to DocumentReference schema (without page_content).
        """
        # Lazy import to avoid circular dependency
        from maru_lang.schemas.chat import DocumentReference

        return DocumentReference(
            id=self.id,
            source=self.source,
            document_id=self.metadata.get("document_id"),
            content=self.page_content,
            group=self.metadata.get("group"),
            file_path=self.metadata.get("file_path")
        )

    def to_reference_response(self) -> dict:
        """ReferenceResponse 형태로 변환"""
        return {
            "source": self.source,
            "code": self.code,
            "page": self.page,
            "page_content": self.page_content,
            "metadata": self.metadata
        }

    def pretty(self) -> str:
        """사용자 친화적 포맷 출력"""
        preview = self.page_content.strip().replace("\n", " ")
        if len(preview) > 50:
            preview = preview[:50] + "..."

        filtered_meta = {
            k: v for k, v in self.metadata.items()
            if v not in (None, "", [], {}, "null", "None")
        }

        meta_lines = "\n".join(
            f"    {k}: {v}" for k, v in filtered_meta.items())

        return (
            f"\n🧩 RetrieveDocument(id={self.id})\n"
            f"📄 Content Preview: {preview}\n"
            f"📎 Metadata:\n{meta_lines}\n"
        )

    @staticmethod
    def sort_by_date(documents: list['RetrieveDocument']) -> list['RetrieveDocument']:
        """문서를 날짜 기준으로 정렬 (최신순)"""

        def parse_date(date_str: str) -> datetime:
            try:
                return datetime.strptime(date_str, "%Y%m%d")
            except:
                return datetime.min

        def get_document_date(doc: 'RetrieveDocument') -> datetime:
            update_date = doc.metadata.get("UpdateDate", "")
            creation_date = doc.metadata.get("CreationDate", "")

            if update_date:
                return parse_date(update_date)
            elif creation_date:
                return parse_date(creation_date)
            return datetime.min

        return sorted(documents, key=get_document_date, reverse=True)
