"""
User Group 관련 서비스 함수들
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
    UserGroup을 이름으로 조회하거나 생성합니다.

    Args:
        name: 그룹 이름 (소문자로 변환됨)

    Returns:
        UserGroup 인스턴스
    """
    name = name.lower()
    user_group, _ = await UserGroup.get_or_create(name=name)
    return user_group


async def get_all_descendant_user_group_ids(group_ids: List[int]) -> set[int]:
    """
    UserGroup 계층 구조를 따라 하위 그룹 ID들을 모두 반환 (자기 자신 포함)

    Args:
        group_ids: 상위 그룹 ID 리스트

    Returns:
        모든 하위 그룹을 포함한 ID set
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
    DocumentGroup 계층 구조를 따라 하위 그룹 ID들을 모두 반환 (자기 자신 포함)

    Args:
        group_ids: 상위 그룹 ID 리스트

    Returns:
        모든 하위 그룹을 포함한 ID set
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
    UserGroup들을 DocumentGroup들과 연결하여 권한을 부여합니다.

    Args:
        user_group_names: 연결할 UserGroup 이름 리스트
        document_group_names: 연결할 DocumentGroup 이름 리스트
        actions: 부여할 권한 액션 리스트 (기본값: [READ, WRITE])
        link_descendants: True일 경우 모든 하위 DocumentGroup도 연결

    Returns:
        연결 결과 딕셔너리:
        {
            "user_groups": 처리된 UserGroup 수,
            "document_groups": 처리된 DocumentGroup 수,
            "permissions_created": 생성된 권한 수,
            "missing_user_groups": 존재하지 않는 UserGroup 이름들,
            "missing_document_groups": 존재하지 않는 DocumentGroup 이름들
        }
    """
    if actions is None:
        actions = [PermissionAction.READ, PermissionAction.WRITE]

    # 소문자로 변환
    user_group_names = [name.lower() for name in user_group_names]
    document_group_names = [name.lower() for name in document_group_names]

    # UserGroup 조회
    user_groups = await UserGroup.filter(name__in=user_group_names).all()
    found_user_group_names = {ug.name for ug in user_groups}
    missing_user_groups = [name for name in user_group_names if name not in found_user_group_names]

    # DocumentGroup 조회
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

    # DocumentGroup ID 목록 준비
    document_group_ids = [dg.id for dg in document_groups]

    # link_descendants가 True인 경우 하위 그룹도 포함
    if link_descendants:
        all_document_group_ids = await get_all_descendant_document_group_ids(document_group_ids)
        document_groups = await DocumentGroup.filter(id__in=all_document_group_ids).all()

    # 권한 생성
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
    UserGroup 이름들이 존재하는지 확인합니다.

    Args:
        user_group_names: 확인할 UserGroup 이름 리스트

    Returns:
        (존재하는 그룹들, 존재하지 않는 그룹들) 튜플
    """
    user_group_names = [name.lower() for name in user_group_names]
    existing_groups = await UserGroup.filter(name__in=user_group_names).values_list("name", flat=True)
    existing_set = set(existing_groups)
    missing_groups = [name for name in user_group_names if name not in existing_set]

    return list(existing_set), missing_groups


async def create_user_groups_if_not_exist(user_group_names: List[str]) -> List[UserGroup]:
    """
    UserGroup들을 생성합니다 (존재하지 않는 경우에만).

    Args:
        user_group_names: 생성할 UserGroup 이름 리스트

    Returns:
        생성되거나 조회된 UserGroup 인스턴스 리스트
    """
    user_groups = []
    for name in user_group_names:
        user_group = await get_or_create_user_group(name)
        user_groups.append(user_group)

    return user_groups


async def get_document_groups_by_names(document_group_names: List[str]) -> List[DocumentGroup]:
    """
    이름으로 DocumentGroup들을 조회합니다.

    Args:
        document_group_names: DocumentGroup 이름 리스트

    Returns:
        DocumentGroup 인스턴스 리스트
    """
    document_group_names = [name.lower() for name in document_group_names]
    return await DocumentGroup.filter(name__in=document_group_names).all()
