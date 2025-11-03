"""
User group management API endpoints
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict, Any

from maru_lang.dependencies.auth import get_user
from maru_lang.services.user_group_command import (
    UserGroupCommandParser,
    execute_user_group_command
)


router = APIRouter(
    prefix="/user-groups",
    tags=["User Groups"]
)


class UserGroupCommandRequest(BaseModel):
    """Request body for user group command"""
    message: str


class UserGroupCommandResponse(BaseModel):
    """Response for user group command"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@router.post("/command", response_model=UserGroupCommandResponse)
async def execute_command(
    request: UserGroupCommandRequest,
    user=Depends(get_user)
):
    """
    Execute user group management command.

    Supports natural language commands in Korean and English:

    ## 그룹 생성
    - `/그룹생성 [그룹명]` or `/create group [name]`

    ## 멤버 관리 (매니저만)
    - `/그룹초대 [그룹명] [이메일]` or `/invite [group] [email]`
    - `/그룹추방 [그룹명] [이메일]` or `/remove [group] [email]`
    - `/그룹위임 [그룹명] [이메일]` or `/transfer [group] [email]`

    ## 그룹 조회
    - `/내그룹목록` or `/my groups`
    - `/관리그룹` or `/managed groups`
    - `/그룹멤버 [그룹명]` or `/members [group]`

    ## 그룹 나가기
    - `/그룹나가기 [그룹명]` or `/leave group [name]`

    Args:
        request: Command request with message
        user: Authenticated user (from token)

    Returns:
        Command execution result with success status and data

    Example:
        ```json
        {
            "message": "/그룹생성 행정팀"
        }
        ```

        Response:
        ```json
        {
            "success": true,
            "message": "Group created successfully",
            "data": {
                "group_id": 123,
                "group_name": "행정팀",
                "created": true
            }
        }
        ```
    """
    try:
        # Parse command
        parsed = UserGroupCommandParser.parse(request.message)

        # Check if it's a valid command
        if parsed["command"] == "unknown":
            return UserGroupCommandResponse(
                success=False,
                message=parsed.get("error", "Unknown command"),
                data={"help": UserGroupCommandParser.get_help_text()}
            )

        # Execute command
        result = await execute_user_group_command(parsed, user.id)

        return UserGroupCommandResponse(**result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute command: {str(e)}"
        )


@router.get("/help")
async def get_help():
    """
    Get help text for user group commands.

    Returns:
        Help text with all available commands and usage examples
    """
    return {
        "help": UserGroupCommandParser.get_help_text()
    }


@router.get("/check-command")
async def check_command(message: str):
    """
    Check if a message is a user group command without executing it.

    Args:
        message: Message to check

    Returns:
        Whether the message is a valid user group command and parsed result
    """
    is_command = UserGroupCommandParser.is_user_group_command(message)
    parsed = UserGroupCommandParser.parse(message) if is_command else None

    return {
        "is_command": is_command,
        "parsed": parsed
    }
