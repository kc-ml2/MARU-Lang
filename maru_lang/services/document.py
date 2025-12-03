from typing import List, Optional, Tuple
from maru_lang.core.relation_db.models.documents import (
    Document,
    DocumentGroup,
    DocumentGroupMembership,
    DocumentGroupInclusion,
    GroupPermission,
    PermissionAction,
)
from maru_lang.core.relation_db.models.auth import UserGroup
from maru_lang.enums.documents import DocumentStatus, SyncMode
from maru_lang.utils.document import new_ulid, make_source_fingerprint_for_file


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


async def get_managed_document_groups(user_id: int) -> List[DocumentGroup]:
    """
    Get all document groups where the user is the manager.

    Args:
        user_id: User ID to check

    Returns:
        List of DocumentGroup instances managed by the user
    """
    return await DocumentGroup.filter(manager_id=user_id).all()


async def get_managed_document_groups_with_stats(user_id: int) -> List[dict]:
    """
    Get top-level document groups where the user is the manager with statistics.
    Only returns groups that are not children of other groups.
    Document count includes all documents in child groups (recursive sum).

    Args:
        user_id: User ID to check

    Returns:
        List of dictionaries containing top-level DocumentGroup info with aggregated stats:
        [
            {
                "id": int,
                "name": str,
                "base_path": str,
                "description": str,
                "document_count": int,  # Sum of this group and all child groups
                "created_at": str
            }
        ]
    """
    # Get all groups managed by user
    all_managed_groups = await DocumentGroup.filter(manager_id=user_id).all()

    if not all_managed_groups:
        return []

    managed_group_ids = {group.id for group in all_managed_groups}

    # Find which groups are children of other groups
    child_group_ids = set()
    parent_child_map = {}  # parent_id -> [child_ids]

    for group_id in managed_group_ids:
        # Check if this group is a child of another managed group
        parent_inclusion = await DocumentGroupInclusion.filter(
            child_id=group_id,
            parent_id__in=managed_group_ids
        ).first()

        if parent_inclusion:
            child_group_ids.add(group_id)

        # Build parent-child mapping for recursive counting
        child_inclusions = await DocumentGroupInclusion.filter(
            parent_id=group_id
        ).all()

        if child_inclusions:
            parent_child_map[group_id] = [inc.child_id for inc in child_inclusions]

    # Top-level groups are those that are NOT children of other managed groups
    top_level_groups = [g for g in all_managed_groups if g.id not in child_group_ids]

    async def get_all_descendant_group_ids(group_id: int, visited: set = None) -> set:
        """Recursively get all descendant group IDs"""
        if visited is None:
            visited = set()

        if group_id in visited:
            return visited

        visited.add(group_id)

        # Get direct children
        child_inclusions = await DocumentGroupInclusion.filter(parent_id=group_id).all()

        for inclusion in child_inclusions:
            if inclusion.child_id not in visited:
                await get_all_descendant_group_ids(inclusion.child_id, visited)

        return visited

    result = []
    for group in top_level_groups:
        # Get all descendant groups (including the group itself)
        all_group_ids = await get_all_descendant_group_ids(group.id)

        # Sum document counts from all groups (parent + children)
        total_doc_count = await DocumentGroupMembership.filter(
            group_id__in=all_group_ids
        ).count()

        result.append({
            "id": group.id,
            "name": group.name,
            "base_path": group.base_path,
            "description": group.description,
            "document_count": total_doc_count,
            "created_at": group.signature_updated_at.isoformat() if group.signature_updated_at else None
        })

    return result


async def upsert_document_group(
    name: str,
    base_path: str,
    manager_id: int,
    rag_components: dict,
    force_new_version: bool = False,
    description: str = None,
    sync_mode: SyncMode = SyncMode.SERVER
) -> tuple[DocumentGroup, bool, bool]:
    """
    DocumentGroup을 upsert (base_path 기준으로 찾아서 업데이트 또는 생성)

    Args:
        name: 그룹 이름 (디렉토리명)
        base_path: 파일시스템 경로 (unique)
        manager_id: 관리자 User ID
        rag_components: 사용된 RAG 컴포넌트 (loader, chunker, embedding_model)
        force_new_version: True일 경우 새 version_id 생성 (re-embed, config 변경 등)
        description: DocumentGroup 설명 (루트 그룹에만 사용)

    Returns:
        Tuple[DocumentGroup, bool, bool]: (그룹 인스턴스, 신규 생성 여부, 설정 변경 여부)
    """
    config_changed = False
    existing_group = await DocumentGroup.get_or_none(base_path=base_path)
    if existing_group and existing_group.manager_id != manager_id:
        raise PermissionError(
            f"Access denied: User {manager_id} does not have permission to update DocumentGroup '{name}' "
            f"(managed by user {existing_group.manager_id})"
        )
    if existing_group and existing_group.rag_components != rag_components:
        force_new_version = True
        config_changed = True

    # base_path가 unique이므로 이걸로 upsert
    defaults = {
        "name": name.lower(),
        "manager_id": manager_id,
        "rag_components": rag_components,
        "sync_mode": sync_mode,
    }

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

    return doc_group, created, config_changed


async def simulate_upsert_document_group(
    name: str,
    base_path: str,
    manager_id: int,
    rag_components: dict,
    force_new_version: bool = False,
    description: str = None
) -> bool:
    """
    DocumentGroup upsert를 시뮬레이션 (DB 변경 없음)

    Args:
        name: 그룹 이름 (디렉토리명)
        base_path: 파일시스템 경로 (unique)
        manager_id: 관리자 User ID
        rag_components: 사용된 RAG 컴포넌트 (loader, chunker, embedding_model)
        force_new_version: True일 경우 새 version_id 생성 (re-embed, config 변경 등)
        description: DocumentGroup 설명 (루트 그룹에만 사용)

    Returns:
        bool: 작업이 필요한지 여부 (True = 생성/업데이트 필요, False = 스킵)
    """
    existing_group = await DocumentGroup.get_or_none(base_path=base_path)

    # 권한 체크 (실제 upsert_document_group과 동일)
    if existing_group and existing_group.manager_id != manager_id:
        raise PermissionError(
            f"Access denied: User {manager_id} does not have permission to update DocumentGroup '{name}' "
            f"(managed by user {existing_group.manager_id})"
        )

    # 신규 생성 필요
    if not existing_group:
        return True

    # 설정 변경 감지
    if existing_group.rag_components != rag_components:
        return True

    # 강제 재처리
    if force_new_version:
        return True

    # 변경 없음
    return False


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

async def get_all_descendant_groups(
    group_names: List[str]
) -> List[DocumentGroup]:
    """
    Resolve all descendant groups starting from the given parents (inclusive).
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

    return all_groups


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
    all_groups = await get_all_descendant_groups(group_names)
    return [group.name for group in all_groups]


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


# ========== Document upsert ==========

async def upsert_document_from_file(
    name: str,
    path: str,
    size: int,
    mtime_ns: int,
    metadata: Optional[dict] = None,
) -> Tuple[Document, bool]:
    """
    파일 기반 문서 업서트

    파일 경로로 Document를 찾고, fingerprint로 변경 여부 확인
    변경된 경우 PROCESSING 상태로 되돌려 재처리 필요함을 표시

    Args:
        name: 문서 이름
        path: 파일 전체 경로
        size: 파일 크기 (bytes)
        mtime_ns: 수정 시간 (nanoseconds)
        metadata: 추가 메타데이터

    Returns:
        Tuple[Document, bool]: (문서, 재처리필요여부)
        - 재처리필요 = True: 신규 생성 또는 파일 수정됨
        - 재처리필요 = False: 기존 파일이고 변경 없음
    """
    fp = make_source_fingerprint_for_file(path, size, mtime_ns)

    # 1. 파일 경로로 기존 Document 조회
    doc = await Document.get_or_none(file_path=path)

    if doc:
        # 2. 기존 문서 존재 → fingerprint 비교
        if doc.source_fingerprint == fp:
            # fingerprint 동일 = 파일 수정 없음 → 재처리 불필요
            doc.name = name or doc.name
            doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
            await doc.save()
            return doc, False

        # fingerprint 다름 = 파일 수정됨 → 재처리 필요
        doc.name = name
        doc.file_size = size
        doc.source_fingerprint = fp
        doc.status = DocumentStatus.PROCESSING  # 재처리 위해 PROCESSING으로
        doc.metadata = {**(doc.metadata or {}), **(metadata or {})}
        await doc.save()
        return doc, True

    # 3. 신규 생성 (PROCESSING 상태)
    new_doc = await Document.create(
        id=new_ulid(),
        name=name,
        file_path=path,
        file_size=size,
        source_fingerprint=fp,
        status=DocumentStatus.PROCESSING,
        metadata=metadata or {},
    )
    return new_doc, True


async def simulate_upsert_document_from_file(
    name: str,
    path: str,
    size: int,
    mtime_ns: int,
    metadata: Optional[dict] = None,
) -> bool:
    """
    파일 기반 문서 업서트를 시뮬레이션 (DB 변경 없음)

    Args:
        name: 문서 이름
        path: 파일 전체 경로
        size: 파일 크기 (bytes)
        mtime_ns: 수정 시간 (nanoseconds)
        metadata: 추가 메타데이터

    Returns:
        bool: 재처리가 필요한지 여부 (True = 생성/업데이트 필요, False = 스킵)
    """
    fp = make_source_fingerprint_for_file(path, size, mtime_ns)
    doc = await Document.get_or_none(file_path=path)

    # 신규 문서
    if not doc:
        return True

    # Fingerprint 비교
    if doc.source_fingerprint != fp:
        return True

    # 변경 없음
    return False


async def update_document_status(doc: Document, status: DocumentStatus) -> None:
    """
    Document 상태 업데이트

    Args:
        doc: 업데이트할 Document
        status: 새로운 상태
    """
    doc.status = status
    await doc.save()


