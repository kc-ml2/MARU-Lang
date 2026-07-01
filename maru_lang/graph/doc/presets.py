"""Document presets for the doc graph.

Classifying the authoring request up front and loading a preset gives the draft a
consistent skeleton (expected sections) plus type-specific guidance, and sets
canvas_type/schema_version deterministically. Adding a document type = adding a
DocPreset entry (mirrors the graph registry's data-driven style — contract is the
first real target; proposal/generic keep the mechanism honest and extensible).
"""
from dataclasses import dataclass


# 문서 이름에 이 중 하나라도 있으면 "표준/템플릿 문서"로 간주(후보군 마커).
DEFAULT_TEMPLATE_MARKERS: tuple[str, ...] = ("표준", "양식", "서식", "template", "standard")


@dataclass(frozen=True)
class DocPreset:
    id: str                          # = canvas_type ("contract")
    label: str                       # 사람이 읽는 이름 ("계약서")
    schema_version: str              # "contract.v1"
    keywords: tuple[str, ...] = ()   # 분류 힌트(키워드 폴백 + classify 프롬프트)
    sections: tuple[dict, ...] = ()  # 권장 섹션 스캐폴드
    parties: tuple[dict, ...] = ()   # 기본 당사자 역할(계약서)
    guidance: str = ""               # 작성 추가 지침
    # 기준 문서 바인딩: family(문서군, AND) + markers(표준/양식, ANY)로 후보를 식별하고,
    # 실제 어떤 표준인지는 요청 문장과의 관련도로 선택한다. family가 비면 바인딩 안 함.
    anchor_family: tuple[str, ...] = ()
    anchor_markers: tuple[str, ...] = DEFAULT_TEMPLATE_MARKERS

    @property
    def canvas_type(self) -> str:
        return self.id

    def scaffold_text(self) -> str:
        """The expected-section skeleton, rendered for the draft prompt."""
        if not self.sections:
            return "(자유 구조)"
        lines = []
        for s in self.sections:
            st = s.get("section_type", "article")
            line = f"- {s.get('title', '')}({st})"
            if s.get("guidance"):
                line += f": {s['guidance']}"
            lines.append(line)
        return "\n".join(lines)

    def to_state(self) -> dict:
        """JSON-serializable form carried in DocState (checkpointer-safe)."""
        return {
            "id": self.id,
            "canvas_type": self.canvas_type,
            "schema_version": self.schema_version,
            "label": self.label,
            "scaffold": self.scaffold_text(),
            "guidance": self.guidance,
            "parties": [dict(p) for p in self.parties],
            "anchor_family": list(self.anchor_family),
            "anchor_markers": list(self.anchor_markers),
        }


DOC_PRESETS: dict[str, DocPreset] = {
    "contract": DocPreset(
        id="contract",
        label="계약서",
        schema_version="contract.v1",
        keywords=("계약", "계약서", "협약", "약정", "용역", "위탁", "contract"),
        sections=(
            {"section_type": "preamble", "title": "전문", "guidance": "계약 당사자와 체결 배경"},
            {"section_type": "article", "title": "본문 조항",
             "guidance": "목적·대금·기간·해지·손해배상 등 핵심 조항"},
            {"section_type": "signature", "title": "서명란", "guidance": "갑·을 서명/날인"},
        ),
        parties=(
            {"label": "갑", "role": "client", "name": "", "address": "", "representative": ""},
            {"label": "을", "role": "vendor", "name": "", "address": "", "representative": ""},
        ),
        guidance=(
            "갑/을 당사자를 명확히 구분하고, 금액·날짜·상대방 정보처럼 아직 확정되지 않은 값은 "
            "placeholder 블록으로 두고 missing_terms에 정리하라."
        ),
        anchor_family=("계약",),
    ),
    "proposal": DocPreset(
        id="proposal",
        label="기안서",
        schema_version="proposal.v1",
        keywords=("기안", "기안서", "품의", "결재", "proposal"),
        sections=(
            {"section_type": "preamble", "title": "제목/개요", "guidance": "기안 제목과 목적"},
            {"section_type": "article", "title": "본문", "guidance": "배경·내용·기대효과"},
            {"section_type": "signature", "title": "결재란", "guidance": "기안/검토/승인"},
        ),
        guidance="결재 흐름을 고려해 간결하게 작성하고, 미정 항목은 missing_terms에 정리하라.",
        anchor_family=("기안",),
    ),
    "generic": DocPreset(
        id="generic",
        label="문서",
        schema_version="document.v1",
        keywords=(),
        sections=(),
        guidance="요청에 맞는 일반 문서를 의미 단위 섹션으로 작성하라.",
    ),
}

DEFAULT_PRESET_ID = "generic"


def get_preset(preset_id: str | None) -> DocPreset:
    """Resolve a preset by id, falling back to the generic preset."""
    return DOC_PRESETS.get(preset_id or "", DOC_PRESETS[DEFAULT_PRESET_ID])


def preset_choices_text() -> str:
    """`id: label (keywords)` lines for the classify prompt."""
    out = []
    for p in DOC_PRESETS.values():
        kw = ", ".join(p.keywords) if p.keywords else "기타/일반"
        out.append(f"- {p.id}: {p.label} ({kw})")
    return "\n".join(out)


def match_by_keyword(instruction: str) -> str | None:
    """Cheap keyword classification fallback over the raw request."""
    t = (instruction or "").lower()
    for p in DOC_PRESETS.values():
        if any(kw.lower() in t for kw in p.keywords):
            return p.id
    return None
