from typing import List
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
    GroupPermission,
    PermissionAction,
)
from maru_lang.core.relation_db.models.auth import UserGroup
from maru_lang.utils.document import new_ulid


# ========== DocumentGroup helpers ==========

async def get_document_group_name(document: Document) -> List[str]:
    """Return all group names associated with the given document."""
    group_membership = await DocumentGroupMembership.filter(
        document=document
    ).select_related("group")

    if not group_membership:
        return []

    return [membership.group.name for membership in group_membership]


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

    groups = await DocumentGroup.filter(
        name__in=group_names
    ).all()

    # Filter out groups without descriptions
    return {
        group.name: group.description
        for group in groups
        if group.description
    }


async def upsert_document_group(
    name: str,
    base_path: str,
    embedding_model: str,
    manager_id: int,
    loader: str = None,
    chunker: str = None,
    config_snapshot: dict = None,
    force_new_version: bool = False,
    description: str = None
) -> tuple[DocumentGroup, bool]:
    """
    DocumentGroup을 upsert (base_path 기준으로 찾아서 업데이트 또는 생성)

    Args:
        name: 그룹 이름 (디렉토리명)
        base_path: 파일시스템 경로 (unique)
        embedding_model: 임베딩 모델명
        manager_id: 관리자 User ID
        loader: 사용된 loader 이름
        chunker: 사용된 chunker 이름
        config_snapshot: 사용된 설정의 스냅샷 (변경 감지용)
        force_new_version: True일 경우 새 version_id 생성 (re-embed, config 변경 등)
        description: DocumentGroup 설명 (루트 그룹에만 사용)

    Returns:
        Tuple[DocumentGroup, bool]: (그룹 인스턴스, 신규 생성 여부)
    """
    # base_path가 unique이므로 이걸로 upsert
    defaults = {
        "name": name.lower(),
        "embedding_model": embedding_model,
        "manager_id": manager_id,
    }

    if loader is not None:
        defaults["loader"] = loader
    if chunker is not None:
        defaults["chunker"] = chunker
    if config_snapshot is not None:
        defaults["config_snapshot"] = config_snapshot
    if description is not None:
        defaults["description"] = description

    doc_group, created = await DocumentGroup.update_or_create(
        base_path=base_path,
        defaults=defaults
    )

    # 신규 생성이거나 force_new_version이면 새 version_id 생성
    if created or force_new_version:
        if not doc_group.version_id or force_new_version:
            doc_group.version_id = new_ulid()
            await doc_group.save()

    return doc_group, created

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

    # 1. Look up DocumentGroup instances by name (convert to lowercase for matching)
    normalized_names = [name.lower() for name in group_names]

    groups = await DocumentGroup.filter(name__in=normalized_names).all()
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
    result_names = [group.name for group in all_groups]

    return result_names


# ========== Permission helpers ==========

async def set_user_group_permissions(
    document_group: DocumentGroup,
    user_group_ids: List[int],
    actions: List[PermissionAction] = None,
    replace: bool = True
) -> dict:
    """
    Set permissions for user groups on a document group.

    Args:
        document_group: DocumentGroup to set permissions on
        user_group_ids: List of UserGroup IDs to grant permissions
        actions: List of permission actions (default: [READ, WRITE])
        replace: If True, remove existing permissions before adding new ones (default: True)

    Returns:
        Dict with 'created' and 'deleted' counts
    """
    if actions is None:
        actions = [PermissionAction.READ, PermissionAction.WRITE]
    permissions_created = 0
    permissions_deleted = 0
    # Replace mode: 기존 권한 삭제
    try:
        if replace:
            deleted_count = await GroupPermission.filter(
                document_group=document_group
            ).delete()
            permissions_deleted = deleted_count

        # 새로운 권한 추가
        for user_group_id in user_group_ids:
            user_group = await UserGroup.get_or_none(id=user_group_id)
            if not user_group:
                continue
            for action in actions:
                _, created = await GroupPermission.get_or_create(
                    user_group=user_group,
                    document_group=document_group,
                    action=action
                )
                if created:
                    permissions_created += 1
    except Exception as e:
        print(f"Error setting user group permissions: {e}")
        raise e
    return {
        "created": permissions_created,
        "deleted": permissions_deleted
    }


