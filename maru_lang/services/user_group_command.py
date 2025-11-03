"""
User group command parser for chat interface.
Parses natural language commands for user group management.
"""
from typing import Optional, Dict, Any
from enum import Enum
import re


class UserGroupCommand(str, Enum):
    """User group command types"""
    CREATE = "create"
    INVITE = "invite"
    REMOVE = "remove"
    LEAVE = "leave"
    TRANSFER = "transfer"
    LIST_MY_GROUPS = "list_my_groups"
    LIST_MEMBERS = "list_members"
    LIST_MANAGED = "list_managed"
    UNKNOWN = "unknown"


class UserGroupCommandParser:
    """Parser for user group commands in chat interface"""

    # Command patterns with Korean and English support
    PATTERNS = {
        UserGroupCommand.CREATE: [
            r"^/?(?:그룹생성|그룹\s*생성|create\s+group)\s+(.+)$",
        ],
        UserGroupCommand.INVITE: [
            r"^/?(?:그룹초대|그룹\s*초대|invite)\s+(.+?)\s+(.+)$",
        ],
        UserGroupCommand.REMOVE: [
            r"^/?(?:그룹추방|그룹\s*추방|그룹제거|그룹\s*제거|remove)\s+(.+?)\s+(.+)$",
        ],
        UserGroupCommand.LEAVE: [
            r"^/?(?:그룹나가기|그룹\s*나가기|leave\s+group)\s+(.+)$",
        ],
        UserGroupCommand.TRANSFER: [
            r"^/?(?:그룹위임|그룹\s*위임|transfer)\s+(.+?)\s+(.+)$",
        ],
        UserGroupCommand.LIST_MY_GROUPS: [
            r"^/?(?:내\s*그룹\s*목록|내그룹목록|내\s*그룹|my\s+groups?)$",
        ],
        UserGroupCommand.LIST_MEMBERS: [
            r"^/?(?:그룹멤버|그룹\s*멤버|members)\s+(.+)$",
        ],
        UserGroupCommand.LIST_MANAGED: [
            r"^/?(?:관리\s*그룹|관리그룹|managed\s+groups?)$",
        ],
    }

    @classmethod
    def parse(cls, message: str) -> Dict[str, Any]:
        """
        Parse user group command from message.

        Args:
            message: User message string

        Returns:
            Dictionary with parsed command:
            {
                "command": UserGroupCommand,
                "params": {...},
                "original_message": str
            }
        """
        message = message.strip()

        # Try to match each command pattern
        for command, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                match = re.match(pattern, message, re.IGNORECASE)
                if match:
                    return cls._build_result(command, match, message)

        # No pattern matched
        return {
            "command": UserGroupCommand.UNKNOWN,
            "params": {},
            "original_message": message,
            "error": "Unknown command format"
        }

    @classmethod
    def _build_result(
        cls,
        command: UserGroupCommand,
        match: re.Match,
        original_message: str
    ) -> Dict[str, Any]:
        """Build result dictionary from matched pattern"""
        result = {
            "command": command,
            "params": {},
            "original_message": original_message
        }

        # Extract parameters based on command type
        groups = match.groups()

        if command == UserGroupCommand.CREATE:
            result["params"]["group_name"] = groups[0].strip()

        elif command == UserGroupCommand.INVITE:
            result["params"]["group_name"] = groups[0].strip()
            result["params"]["user_email"] = groups[1].strip()

        elif command == UserGroupCommand.REMOVE:
            result["params"]["group_name"] = groups[0].strip()
            result["params"]["user_email"] = groups[1].strip()

        elif command == UserGroupCommand.LEAVE:
            result["params"]["group_name"] = groups[0].strip()

        elif command == UserGroupCommand.TRANSFER:
            result["params"]["group_name"] = groups[0].strip()
            result["params"]["new_manager_email"] = groups[1].strip()

        elif command == UserGroupCommand.LIST_MEMBERS:
            result["params"]["group_name"] = groups[0].strip()

        # LIST_MY_GROUPS and LIST_MANAGED have no parameters

        return result

    @classmethod
    def is_user_group_command(cls, message: str) -> bool:
        """
        Check if message is a user group command.

        Args:
            message: User message string

        Returns:
            True if message matches any user group command pattern
        """
        message = message.strip()
        for patterns in cls.PATTERNS.values():
            for pattern in patterns:
                if re.match(pattern, message, re.IGNORECASE):
                    return True
        return False

    @classmethod
    def get_help_text(cls) -> str:
        """
        Get help text for user group commands.

        Returns:
            Formatted help text string
        """
        return """
# 사용자 그룹 관리 명령어

## 그룹 생성
- `/그룹생성 [그룹명]` - 새 그룹 생성 (예: /그룹생성 행정팀)

## 멤버 관리 (매니저만 가능)
- `/그룹초대 [그룹명] [이메일]` - 사용자 초대 (예: /그룹초대 행정팀 user@example.com)
- `/그룹추방 [그룹명] [이메일]` - 멤버 제거 (예: /그룹추방 행정팀 user@example.com)
- `/그룹위임 [그룹명] [이메일]` - 매니저 권한 위임 (예: /그룹위임 행정팀 newmanager@example.com)

## 그룹 조회
- `/내그룹목록` - 내가 속한 그룹 목록
- `/관리그룹` - 내가 매니저인 그룹 목록
- `/그룹멤버 [그룹명]` - 그룹 멤버 목록 (예: /그룹멤버 행정팀)

## 그룹 나가기
- `/그룹나가기 [그룹명]` - 그룹에서 나가기 (예: /그룹나가기 행정팀)
  * 주의: public 및 도메인 그룹은 나갈 수 없습니다

---
영어 명령어도 지원됩니다:
- `/create group [name]`
- `/invite [group] [email]`
- `/remove [group] [email]`
- `/transfer [group] [email]`
- `/my groups`
- `/managed groups`
- `/members [group]`
- `/leave group [name]`
""".strip()


async def execute_user_group_command(
    command_result: Dict[str, Any],
    user_id: int
) -> Dict[str, Any]:
    """
    Execute parsed user group command.

    Args:
        command_result: Parsed command result from UserGroupCommandParser.parse()
        user_id: Current user's ID

    Returns:
        Dictionary with execution result:
        {
            "success": bool,
            "message": str,
            "data": {...}  # Optional, command-specific data
        }
    """
    from maru_lang.services.user_group import (
        create_user_group,
        invite_user_to_group,
        remove_user_from_group,
        leave_group,
        transfer_group_manager,
        get_managed_user_groups,
    )
    from maru_lang.services.auth import get_user_groups
    from maru_lang.core.relation_db.models.auth import User, UserGroup, UserGroupMembership

    command = command_result["command"]
    params = command_result["params"]

    try:
        # CREATE - 그룹 생성
        if command == UserGroupCommand.CREATE:
            group_name = params["group_name"]
            group, created, message = await create_user_group(group_name, user_id)

            return {
                "success": created,
                "message": message,
                "data": {
                    "group_id": group.id,
                    "group_name": group.name,
                    "created": created
                }
            }

        # INVITE - 사용자 초대
        elif command == UserGroupCommand.INVITE:
            group_name = params["group_name"]
            user_email = params["user_email"]

            # Get group by name
            group = await UserGroup.get_or_none(name=group_name.lower())
            if not group:
                return {
                    "success": False,
                    "message": f"그룹 '{group_name}'을 찾을 수 없습니다."
                }

            success, message = await invite_user_to_group(
                group.id,
                user_id,
                user_email
            )

            return {
                "success": success,
                "message": message,
                "data": {"group_name": group.name}
            }

        # REMOVE - 멤버 제거
        elif command == UserGroupCommand.REMOVE:
            group_name = params["group_name"]
            user_email = params["user_email"]

            group = await UserGroup.get_or_none(name=group_name.lower())
            if not group:
                return {
                    "success": False,
                    "message": f"그룹 '{group_name}'을 찾을 수 없습니다."
                }

            success, message = await remove_user_from_group(
                group.id,
                user_id,
                user_email
            )

            return {
                "success": success,
                "message": message,
                "data": {"group_name": group.name}
            }

        # LEAVE - 그룹 나가기
        elif command == UserGroupCommand.LEAVE:
            group_name = params["group_name"]

            group = await UserGroup.get_or_none(name=group_name.lower())
            if not group:
                return {
                    "success": False,
                    "message": f"그룹 '{group_name}'을 찾을 수 없습니다."
                }

            success, message = await leave_group(user_id, group.id)

            return {
                "success": success,
                "message": message,
                "data": {"group_name": group.name}
            }

        # TRANSFER - 매니저 위임
        elif command == UserGroupCommand.TRANSFER:
            group_name = params["group_name"]
            new_manager_email = params["new_manager_email"]

            group = await UserGroup.get_or_none(name=group_name.lower())
            if not group:
                return {
                    "success": False,
                    "message": f"그룹 '{group_name}'을 찾을 수 없습니다."
                }

            success, message = await transfer_group_manager(
                group.id,
                user_id,
                new_manager_email
            )

            return {
                "success": success,
                "message": message,
                "data": {"group_name": group.name}
            }

        # LIST_MY_GROUPS - 내 그룹 목록
        elif command == UserGroupCommand.LIST_MY_GROUPS:
            user = await User.get(id=user_id)
            groups = await get_user_groups(user)

            group_list = []
            for group in groups:
                is_manager = group.manager_id == user_id
                group_list.append({
                    "id": group.id,
                    "name": group.name,
                    "is_manager": is_manager,
                    "created_at": group.created_at.isoformat() if hasattr(group, 'created_at') and group.created_at else None
                })

            return {
                "success": True,
                "message": f"총 {len(group_list)}개의 그룹에 속해 있습니다.",
                "data": {
                    "groups": group_list,
                    "total": len(group_list)
                }
            }

        # LIST_MANAGED - 관리 그룹 목록
        elif command == UserGroupCommand.LIST_MANAGED:
            managed_groups = await get_managed_user_groups(user_id)

            group_list = []
            for group in managed_groups:
                # Count members
                member_count = await UserGroupMembership.filter(group_id=group.id).count()
                group_list.append({
                    "id": group.id,
                    "name": group.name,
                    "member_count": member_count,
                    "created_at": group.created_at.isoformat() if hasattr(group, 'created_at') and group.created_at else None
                })

            return {
                "success": True,
                "message": f"총 {len(group_list)}개의 그룹을 관리하고 있습니다.",
                "data": {
                    "groups": group_list,
                    "total": len(group_list)
                }
            }

        # LIST_MEMBERS - 그룹 멤버 목록
        elif command == UserGroupCommand.LIST_MEMBERS:
            group_name = params["group_name"]

            group = await UserGroup.get_or_none(name=group_name.lower()).prefetch_related('manager')
            if not group:
                return {
                    "success": False,
                    "message": f"그룹 '{group_name}'을 찾을 수 없습니다."
                }

            # Get all members
            memberships = await UserGroupMembership.filter(
                group_id=group.id
            ).prefetch_related('user')

            member_list = []
            for membership in memberships:
                user = membership.user
                is_manager = user.id == group.manager_id
                member_list.append({
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "is_manager": is_manager
                })

            return {
                "success": True,
                "message": f"그룹 '{group.name}'의 멤버 목록 ({len(member_list)}명)",
                "data": {
                    "group_name": group.name,
                    "members": member_list,
                    "total": len(member_list)
                }
            }

        # UNKNOWN
        else:
            return {
                "success": False,
                "message": "알 수 없는 명령어입니다. 도움말을 보려면 '/그룹도움말'을 입력하세요.",
                "data": {}
            }

    except Exception as e:
        return {
            "success": False,
            "message": f"명령 실행 중 오류가 발생했습니다: {str(e)}",
            "error": str(e)
        }
