from typing import List, Optional, Tuple
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.utils.document import new_ulid, make_source_fingerprint_for_file


# ========== DocumentGroup helpers ==========

async def get_document_group_descriptions(group_names: List[str]) -> dict[str, str]:
    """
    Get descriptions for document groups from DB.

    Args:
        group_names: List of group names to fetch descriptions for

    Returns:
        Dict mapping group_name to description (only includes groups with descriptions)
    """
    if not group_names:
        return {}

    groups = await DocumentGroup.filter(name__in=group_names).all()

    return {
        group.name: group.description
        for group in groups
        if group.description
    }


async def get_or_create_document_group(
    team_id: int,
    name: str,
    parent: Optional[DocumentGroup] = None,
    description: Optional[str] = None,
    rag_components: Optional[dict] = None,
) -> Tuple[DocumentGroup, bool]:
    """
    DocumentGroup을 조회하거나 생성

    Args:
        team_id: Team ID
        name: 그룹 이름
        parent: 부모 그룹 (없으면 루트)
        description: 설명
        rag_components: RAG 설정

    Returns:
        Tuple[DocumentGroup, bool]: (그룹 인스턴스, 신규 생성 여부)
    """
    defaults = {
        "description": description,
        "rag_components": rag_components or {},
    }

    group, created = await DocumentGroup.get_or_create(
        team_id=team_id,
        name=name,
        parent=parent,
        defaults=defaults
    )

    return group, created


async def get_all_descendant_groups(group: DocumentGroup) -> List[DocumentGroup]:
    """
    주어진 그룹의 모든 하위 그룹을 재귀적으로 조회

    Args:
        group: 시작 그룹

    Returns:
        하위 그룹 리스트 (자신 포함)
    """
    result = [group]
    children = await DocumentGroup.filter(parent=group).all()

    for child in children:
        descendants = await get_all_descendant_groups(child)
        result.extend(descendants)

    return result


async def get_all_descendant_group_names(group_names: List[str]) -> List[str]:
    """
    주어진 그룹들의 모든 하위 그룹 이름을 재귀적으로 조회

    Args:
        group_names: 시작 그룹 이름들

    Returns:
        모든 하위 그룹 이름 리스트 (자신 포함)
    """
    result = set()

    for name in group_names:
        group = await DocumentGroup.get_or_none(name=name)
        if group:
            descendants = await get_all_descendant_groups(group)
            result.update(g.name for g in descendants)

    return list(result)


async def get_groups_with_descendants(group_names: List[str]) -> List[DocumentGroup]:
    """
    주어진 그룹 이름들의 DocumentGroup 객체와 모든 하위 그룹을 조회

    Args:
        group_names: 그룹 이름 리스트

    Returns:
        DocumentGroup 객체 리스트 (하위 그룹 포함)
    """
    result = []

    for name in group_names:
        group = await DocumentGroup.get_or_none(name=name)
        if group:
            descendants = await get_all_descendant_groups(group)
            result.extend(descendants)

    # 중복 제거
    seen = set()
    unique_result = []
    for g in result:
        if g.id not in seen:
            seen.add(g.id)
            unique_result.append(g)

    return unique_result


async def get_groups_by_team_id(team_id: int) -> List[DocumentGroup]:
    """
    Team ID로 접근 가능한 모든 DocumentGroup 조회

    Args:
        team_id: Team ID

    Returns:
        해당 Team의 모든 DocumentGroup 리스트
    """
    return await DocumentGroup.filter(team_id=team_id).all()


async def get_group_names_by_team_id(team_id: int, with_documents_only: bool = True) -> List[str]:
    """
    Team ID로 접근 가능한 DocumentGroup 이름 조회

    Args:
        team_id: Team ID
        with_documents_only: True면 문서가 있는 그룹만 반환

    Returns:
        DocumentGroup 이름 리스트
    """
    if with_documents_only:
        # Only return groups that have at least one document
        groups = await DocumentGroup.filter(
            team_id=team_id,
            documents__isnull=False
        ).distinct().values_list("name", flat=True)
    else:
        groups = await DocumentGroup.filter(team_id=team_id).values_list("name", flat=True)
    return [str(name) for name in groups]


# ========== Document helpers ==========

async def upsert_document_from_file(
    group: DocumentGroup,
    name: str,
    path: str,
    size: int,
    mtime_ns: int,
    metadata: Optional[dict] = None,
    rag_components: Optional[dict] = None,
) -> Tuple[Document, bool]:
    """
    파일 기반 문서 업서트

    Args:
        group: 소속 DocumentGroup
        name: 문서 이름
        path: 파일 전체 경로
        size: 파일 크기 (bytes)
        mtime_ns: 수정 시간 (nanoseconds)
        metadata: 추가 메타데이터
        rag_components: RAG 설정 (없으면 자동 감지)

    Returns:
        Tuple[Document, bool]: (문서, 재처리필요여부)
    """
    fp = make_source_fingerprint_for_file(path, size, mtime_ns)

    doc = await Document.get_or_none(file_path=path)

    if doc:
        if doc.source_fingerprint == fp:
            doc.name = name or doc.name
            doc.group = group
            doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
            await doc.save()
            return doc, False

        doc.name = name
        doc.group = group
        doc.file_size = size
        doc.source_fingerprint = fp
        doc.status = DocumentStatus.PROCESSING
        doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
        doc.rag_components = rag_components or {}
        await doc.save()
        return doc, True

    new_doc = await Document.create(
        id=new_ulid(),
        name=name,
        group=group,
        file_path=path,
        file_size=size,
        source_fingerprint=fp,
        status=DocumentStatus.PROCESSING,
        metadata=metadata or {},
        rag_components=rag_components or {},
    )
    return new_doc, True


async def update_document_status(doc: Document, status: DocumentStatus) -> None:
    """Document 상태 업데이트"""
    doc.status = status
    await doc.save()
