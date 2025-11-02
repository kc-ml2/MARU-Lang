"""
Service helpers related to user groups and their permissions.
"""
from typing import List, Optional
from tortoise.exceptions import DoesNotExist
from maru_lang.core.relation_db.models.auth import (
    UserGroup,
    UserGroupInclusion,
)
from maru_lang.core.relation_db.models.documents import (
    DocumentGroup,
    DocumentGroupInclusion,
    GroupPermission,
    PermissionAction,
)


async def get_or_create_user_group(name: str) -> UserGroup:
    """
    Retrieve a user group by name, creating it if necessary.

    Args:
        name: Group name (case-insensitive; stored as lowercase).

    Returns:
        The fetched or newly created ``UserGroup`` instance.
    """
    name = name.lower()
    user_group, _ = await UserGroup.get_or_create(name=name)
    return user_group


async def get_all_descendant_user_group_ids(group_ids: List[int]) -> set[int]:
    """
    Traverse the user-group hierarchy and return every descendant ID, including the originals.

    Args:
        group_ids: List of parent group IDs.

    Returns:
        A set containing all descendant group IDs.
    """
    seen = set(group_ids)
    queue = list(group_ids)

    while queue:
        current = queue.pop()
        children = await UserGroupInclusion.filter(parent_id=current).values_list("child_id", flat=True)
        for child in children:
            if child not in seen:
                seen.add(child)
                queue.append(child)

    return seen


async def get_all_descendant_document_group_ids(group_ids: List[int]) -> set[int]:
    """
    Traverse the document-group hierarchy and return every descendant ID, including the originals.

    Args:
        group_ids: List of parent document group IDs.

    Returns:
        A set containing all descendant document group IDs.
    """
    seen = set(group_ids)
    queue = list(group_ids)

    while queue:
        current = queue.pop()
        children = await DocumentGroupInclusion.filter(parent_id=current).values_list("child_id", flat=True)
        for child in children:
            if child not in seen:
                seen.add(child)
                queue.append(child)

    return seen


async def link_user_groups_to_document_groups(
    user_group_names: List[str],
    document_group_names: List[str],
    actions: List[PermissionAction] = None,
    link_descendants: bool = False,
) -> dict:
    """
    Grant permissions by linking user groups to document groups.

    Args:
        user_group_names: Names of user groups to connect.
        document_group_names: Names of document groups to connect.
        actions: Permission actions to grant (defaults to ``[READ, WRITE]``).
        link_descendants: When ``True``, include all descendant document groups.

    Returns:
        Dictionary summarizing the operation::

            {
                "user_groups": count of processed user groups,
                "document_groups": count of processed document groups,
                "permissions_created": number of new permissions created,
                "missing_user_groups": names that were not found,
                "missing_document_groups": names that were not found,
            }
    """
    if actions is None:
        actions = [PermissionAction.READ, PermissionAction.WRITE]

    # Normalize names to lowercase to avoid case-sensitivity issues
    user_group_names = [name.lower() for name in user_group_names]
    document_group_names = [name.lower() for name in document_group_names]

    # Fetch existing user groups
    user_groups = await UserGroup.filter(name__in=user_group_names).all()
    found_user_group_names = {ug.name for ug in user_groups}
    missing_user_groups = [name for name in user_group_names if name not in found_user_group_names]

    # Fetch existing document groups
    document_groups = await DocumentGroup.filter(name__in=document_group_names).all()
    found_document_group_names = {dg.name for dg in document_groups}
    missing_document_groups = [name for name in document_group_names if name not in found_document_group_names]

    if not user_groups:
        return {
            "user_groups": 0,
            "document_groups": len(document_groups),
            "permissions_created": 0,
            "missing_user_groups": missing_user_groups,
            "missing_document_groups": missing_document_groups,
            "error": "No valid user groups found"
        }

    if not document_groups:
        return {
            "user_groups": len(user_groups),
            "document_groups": 0,
            "permissions_created": 0,
            "missing_user_groups": missing_user_groups,
            "missing_document_groups": missing_document_groups,
            "error": "No valid document groups found"
        }

    # Prepare document-group ID list
    document_group_ids = [dg.id for dg in document_groups]

    # Optionally include descendant groups
    if link_descendants:
        all_document_group_ids = await get_all_descendant_document_group_ids(document_group_ids)
        document_groups = await DocumentGroup.filter(id__in=all_document_group_ids).all()

    # Create group permissions
    permissions_created = 0
    for user_group in user_groups:
        for document_group in document_groups:
            for action in actions:
                _, created = await GroupPermission.get_or_create(
                    user_group=user_group,
                    document_group=document_group,
                    action=action
                )
                if created:
                    permissions_created += 1

    return {
        "user_groups": len(user_groups),
        "document_groups": len(document_groups),
        "permissions_created": permissions_created,
        "missing_user_groups": missing_user_groups,
        "missing_document_groups": missing_document_groups
    }


async def validate_user_groups_exist(user_group_names: List[str]) -> tuple[List[str], List[str]]:
    """
    Check whether the provided user group names exist.

    Args:
        user_group_names: Names of user groups to validate.

    Returns:
        A tuple ``(existing_groups, missing_groups)``.
    """
    user_group_names = [name.lower() for name in user_group_names]
    existing_groups = await UserGroup.filter(name__in=user_group_names).values_list("name", flat=True)
    existing_set = set(existing_groups)
    missing_groups = [name for name in user_group_names if name not in existing_set]

    return list(existing_set), missing_groups


async def create_user_groups_if_not_exist(user_group_names: List[str]) -> List[UserGroup]:
    """
    Ensure that the given user groups exist, creating any missing ones.

    Args:
        user_group_names: Names of user groups to create or fetch.

    Returns:
        List of ``UserGroup`` instances that now exist.
    """
    user_groups = []
    for name in user_group_names:
        user_group = await get_or_create_user_group(name)
        user_groups.append(user_group)

    return user_groups


async def get_document_groups_by_names(document_group_names: List[str]) -> List[DocumentGroup]:
    """
    Retrieve document groups matching the given names.

    Args:
        document_group_names: Names of document groups to fetch.

    Returns:
        List of matching ``DocumentGroup`` instances.
    """
    document_group_names = [name.lower() for name in document_group_names]
    return await DocumentGroup.filter(name__in=document_group_names).all()


async def get_user_accessible_document_groups(user_id: int) -> List[str]:
    """
    Get all document group names that a user can access.

    This includes:
    1. Groups directly linked to user's groups via GroupPermission
    2. All descendant document groups (via DocumentGroupInclusion)

    Args:
        user_id: User ID to check permissions for

    Returns:
        List of document group names the user can access
    """
    from maru_lang.core.relation_db.models.auth import User, UserGroupMembership

    # Get user's group memberships
    user_group_ids = await UserGroupMembership.filter(
        user_id=user_id
    ).values_list("group_id", flat=True)

    if not user_group_ids:
        return []

    # Get all descendant user groups (including the user's direct groups)
    all_user_group_ids = await get_all_descendant_user_group_ids(list(user_group_ids))

    # Get document groups that these user groups have READ permission to
    permitted_doc_group_ids = await GroupPermission.filter(
        user_group_id__in=all_user_group_ids,
        action=PermissionAction.READ
    ).values_list("document_group_id", flat=True)

    if not permitted_doc_group_ids:
        return []

    # Get all descendant document groups (including the directly permitted ones)
    all_doc_group_ids = await get_all_descendant_document_group_ids(list(permitted_doc_group_ids))

    # Get the names of all accessible document groups
    doc_group_names = await DocumentGroup.filter(
        id__in=all_doc_group_ids
    ).values_list("name", flat=True)

    return list(doc_group_names)
