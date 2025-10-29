from typing import List
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
)


# ========== DocumentGroup 관련 ==========

async def get_document_group_name(document: Document) -> List[str]:
    """문서의 첫 번째 그룹명 반환"""
    group_membership = await DocumentGroupMembership.filter(
        document=document
    ).select_related("group")

    if not group_membership:
        return []

    return [membership.group.name for membership in group_membership]


async def get_or_create_document_group(name: str) -> DocumentGroup:
    # only lowercase
    doc_group, _ = await DocumentGroup.get_or_create(name=name.lower())
    return doc_group

async def set_document_group_inclusion(
    parent_group: DocumentGroup, 
    child_group: DocumentGroup
):
    await DocumentGroupInclusion.get_or_create(parent=parent_group, child=child_group)


async def get_all_descendant_group_ids(
    group_ids: list[int], *, inclusion_model
) -> set[int]:
    """
    계층 구조를 따라 하위 그룹 id들을 모두 반환 (자기 자신 포함)
    """
    seen = set(group_ids)
    queue = list(group_ids)

    while queue:
        current = queue.pop()
        children = await inclusion_model.filter(parent_id=current).values_list("child_id", flat=True)
        for child in children:
            if child not in seen:
                seen.add(child)
                queue.append(child)

    return seen


async def get_all_descendant_group_names(
    group_names: List[str]
) -> List[str]:
    """
    그룹 이름 기반으로 계층 구조를 따라 하위 그룹 이름들을 모두 반환 (자기 자신 포함)

    Args:
        group_names: 상위 그룹 이름 리스트

    Returns:
        모든 하위 그룹 포함한 그룹 이름 리스트
    """
    if not group_names:
        return []

    # 1. 그룹 이름으로 DocumentGroup 조회
    groups = await DocumentGroup.filter(name__in=group_names).all()
    if not groups:
        return []

    # 2. ID로 변환
    group_ids = [group.id for group in groups]

    # 3. 모든 자식 ID 가져오기
    all_group_ids = await get_all_descendant_group_ids(
        group_ids,
        inclusion_model=DocumentGroupInclusion
    )

    # 4. ID를 다시 이름으로 변환
    all_groups = await DocumentGroup.filter(id__in=all_group_ids).all()
    return [group.name for group in all_groups]


