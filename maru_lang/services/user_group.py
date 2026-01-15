"""
Service helpers related to user groups and their permissions.
"""
from typing import List, Optional
from tortoise.exceptions import DoesNotExist
from maru_lang.core.relation_db.models.auth import (
    User,
    UserGroup,
    UserGroupMembership
)
from maru_lang.core.relation_db.models.documents import (
    DocumentGroup,
    DocumentGroupInclusion,
    GroupPermission,
    PermissionAction,
)


async def get_or_create_user_group(name: str, manager_id: Optional[int] = None) -> UserGroup:
    """
    Retrieve a user group by name, creating it if necessary.

    Args:
        name: Group name (case-insensitive; stored as lowercase).
        manager_id: User ID who will be the manager (required when creating new group).

    Returns:
        The fetched or newly created ``UserGroup`` instance.
    """
    name = name.lower()
    defaults = {}
    if manager_id is not None:
        defaults["manager_id"] = manager_id
    user_group, _ = await UserGroup.get_or_create(name=name, defaults=defaults)
    return user_group


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
    missing_user_groups = [
        name for name in user_group_names if name not in found_user_group_names]

    # Fetch existing document groups
    document_groups = await DocumentGroup.filter(name__in=document_group_names).all()
    found_document_group_names = {dg.name for dg in document_groups}
    missing_document_groups = [
        name for name in document_group_names if name not in found_document_group_names]

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
    missing_groups = [
        name for name in user_group_names if name not in existing_set]

    return list(existing_set), missing_groups


async def create_user_groups_if_not_exist(user_group_names: List[str], manager_id: Optional[int] = None) -> List[UserGroup]:
    """
    Ensure that the given user groups exist, creating any missing ones.

    Args:
        user_group_names: Names of user groups to create or fetch.
        manager_id: User ID who will be the manager for newly created groups.

    Returns:
        List of ``UserGroup`` instances that now exist.
    """
    user_groups = []
    for name in user_group_names:
        user_group = await get_or_create_user_group(name, manager_id=manager_id)
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


async def is_user_group_manager(user_id: int, group_id: int) -> bool:
    """
    Check if a user is the manager of a specific user group.

    Args:
        user_id: User ID to check
        group_id: UserGroup ID to check

    Returns:
        True if the user is the manager of the group, False otherwise
    """
    group = await UserGroup.get_or_none(id=group_id, manager_id=user_id)
    return group is not None


async def get_managed_user_groups(user_id: int) -> List[UserGroup]:
    """
    Get all user groups where the user is the manager.

    Args:
        user_id: User ID to check

    Returns:
        List of UserGroup instances managed by the user
    """
    return await UserGroup.filter(manager_id=user_id).all()


async def create_user_group(name: str, creator_id: int) -> tuple[UserGroup, bool, str]:
    """
    Create a new user group with the creator as manager.
    Automatically creates inclusion relationship with creator's domain group (not public).

    Args:
        name: Group name (case-insensitive; stored as lowercase).
        creator_id: User ID who creates the group and becomes the manager.

    Returns:
        Tuple of (UserGroup instance, created flag, message)
        - If group already exists: (existing_group, False, "Group already exists")
        - If created successfully: (new_group, True, "Group created successfully")
    """

    name = name.lower()

    # Check if group already exists
    existing_group = await UserGroup.get_or_none(name=name)
    if existing_group:
        return existing_group, False, "Group already exists"

    # Create new group with creator as manager
    new_group = await UserGroup.create(
        name=name,
        manager_id=creator_id
    )

    # Automatically add creator to the group
    creator = await User.get(id=creator_id)
    await UserGroupMembership.create(user=creator, group=new_group)

    return new_group, True, "Group created successfully"


async def invite_user_to_group(
    group_id: int,
    inviter_id: int,
    invitee_email: str
) -> tuple[bool, str]:
    """
    Invite a user to a group. Only the group manager can invite users.

    Args:
        group_id: UserGroup ID to invite user to
        inviter_id: User ID who is inviting (must be manager)
        invitee_email: Email of user to invite

    Returns:
        Tuple of (success flag, message)
    """

    # Check if inviter is the manager
    is_manager = await is_user_group_manager(inviter_id, group_id)
    if not is_manager:
        return False, "Only group manager can invite users"

    # Get the group
    group = await UserGroup.get_or_none(id=group_id)
    if not group:
        return False, "Group not found"

    # Get the invitee user
    invitee = await User.get_or_none(email=invitee_email.lower())
    if not invitee:
        return False, f"User with email {invitee_email} not found"

    # Check if user is already in the group
    existing_membership = await UserGroupMembership.get_or_none(
        user_id=invitee.id,
        group_id=group_id
    )
    if existing_membership:
        return False, "User is already in the group"

    # Add user to group
    await UserGroupMembership.create(user=invitee, group=group)

    return True, f"User {invitee_email} added to group {group.name}"


async def transfer_group_manager(
    group_id: int,
    current_manager_id: int,
    new_manager_email: str
) -> tuple[bool, str]:
    """
    Transfer group manager role to another user. Only current manager can transfer.

    Args:
        group_id: UserGroup ID
        current_manager_id: Current manager's user ID
        new_manager_email: Email of user to become new manager

    Returns:
        Tuple of (success flag, message)
    """

    # Check if current user is the manager
    is_manager = await is_user_group_manager(current_manager_id, group_id)
    if not is_manager:
        return False, "Only group manager can transfer manager role"

    # Get the group
    group = await UserGroup.get_or_none(id=group_id)
    if not group:
        return False, "Group not found"

    # Get the new manager user
    new_manager = await User.get_or_none(email=new_manager_email.lower())
    if not new_manager:
        return False, f"User with email {new_manager_email} not found"

    # Check if new manager is in the group
    membership = await UserGroupMembership.get_or_none(
        user_id=new_manager.id,
        group_id=group_id
    )
    if not membership:
        return False, "New manager must be a member of the group first"

    # Transfer manager role
    group.manager_id = new_manager.id
    await group.save()

    return True, f"Manager role transferred to {new_manager_email}"


async def remove_user_from_group(
    group_id: int,
    manager_id: int,
    user_email: str
) -> tuple[bool, str]:
    """
    Remove a user from a group. Only the group manager can remove users.

    Args:
        group_id: UserGroup ID
        manager_id: Manager's user ID
        user_email: Email of user to remove

    Returns:
        Tuple of (success flag, message)
    """

    # Check if requester is the manager
    is_manager = await is_user_group_manager(manager_id, group_id)
    if not is_manager:
        return False, "Only group manager can remove users"

    # Get the group
    group = await UserGroup.get_or_none(id=group_id)
    if not group:
        return False, "Group not found"

    # Get the user to remove
    user_to_remove = await User.get_or_none(email=user_email.lower())
    if not user_to_remove:
        return False, f"User with email {user_email} not found"

    # Cannot remove the manager
    if user_to_remove.id == manager_id:
        return False, "Manager cannot remove themselves. Transfer manager role first."

    # Remove user from group
    deleted_count = await UserGroupMembership.filter(
        user_id=user_to_remove.id,
        group_id=group_id
    ).delete()

    if deleted_count == 0:
        return False, "User is not in the group"

    return True, f"User {user_email} removed from group {group.name}"


async def leave_group(user_id: int, group_id: int) -> tuple[bool, str]:
    """
    Allow a user to leave a group.
    Cannot leave public or domain groups (groups managed by admin).

    Args:
        user_id: User ID who wants to leave
        group_id: UserGroup ID to leave

    Returns:
        Tuple of (success flag, message)
    """
    from maru_lang.services.admin import ADMIN_EMAIL

    # Get the group
    group = await UserGroup.get_or_none(id=group_id).prefetch_related('manager')
    if not group:
        return False, "Group not found"

    # Check if group is managed by admin (public or domain groups)
    admin_user = await User.get_or_none(email=ADMIN_EMAIL)
    if admin_user and group.manager_id == admin_user.id:
        return False, "Cannot leave public or domain groups"

    # Check if user is the manager
    if group.manager_id == user_id:
        # Count total members
        member_count = await UserGroupMembership.filter(group_id=group_id).count()
        if member_count > 1:
            return False, "Manager must transfer manager role before leaving the group"
        # If manager is the only member, allow leaving (group will be orphaned but that's ok)

    # Remove user from group
    deleted_count = await UserGroupMembership.filter(
        user_id=user_id,
        group_id=group_id
    ).delete()

    if deleted_count == 0:
        return False, "User is not in the group"

    return True, f"Successfully left group {group.name}"


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

    # Get user's group memberships
    user_group_ids = await UserGroupMembership.filter(
        user_id=user_id
    ).values_list("group_id", flat=True)
    if not user_group_ids:
        return []

    # temporary block
    return []
    # Get all descendant user groups (including the user's direct groups)
    # all_user_group_ids = await get_all_descendant_user_group_ids(list(user_group_ids))
    # # Get document groups that these user groups have READ permission to
    # permitted_doc_group_ids = await GroupPermission.filter(
    #     user_group_id__in=all_user_group_ids,
    #     action=PermissionAction.READ
    # ).values_list("document_group_id", flat=True)
    # if not permitted_doc_group_ids:
    #     return []

    # # Get all descendant document groups (including the directly permitted ones)
    # all_doc_group_ids = await get_all_descendant_document_group_ids(list(permitted_doc_group_ids))

    # # Get the names of all accessible document groups
    # doc_group_names = await DocumentGroup.filter(
    #     id__in=all_doc_group_ids
    # ).values_list("name", flat=True)
    # return list(doc_group_names)
