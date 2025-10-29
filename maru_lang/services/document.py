from typing import List
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
)


# ========== DocumentGroup helpers ==========

async def get_document_group_name(document: Document) -> List[str]:
    """Return all group names associated with the given document."""
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
    Walk the hierarchy and return every descendant group ID, including the originals.
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
    Resolve all descendant group names starting from the given parents (inclusive).

    Args:
        group_names: Parent group names.

    Returns:
        List of group names including every descendant.
    """
    if not group_names:
        return []

    # 1. Look up DocumentGroup instances by name
    groups = await DocumentGroup.filter(name__in=group_names).all()
    if not groups:
        return []

    # 2. Convert to IDs
    group_ids = [group.id for group in groups]

    # 3. Fetch all descendant IDs
    all_group_ids = await get_all_descendant_group_ids(
        group_ids,
        inclusion_model=DocumentGroupInclusion
    )

    # 4. Convert IDs back to names
    all_groups = await DocumentGroup.filter(id__in=all_group_ids).all()
    return [group.name for group in all_groups]


