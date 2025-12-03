"""
Sync helper functions for request-response patterns
"""
from typing import Any
from maru_lang.dependencies.sync import get_sync_manager


async def sync_request(
    user_id: int,
    action: str,
    data: dict | None = None,
    timeout: float = 30.0
) -> Any:
    """
    동기적으로 클라이언트에게 요청을 보내고 응답을 기다림

    Args:
        user_id: 대상 유저 ID
        action: 수행할 액션 (예: "delete_chunks", "add_documents")
        data: 추가 데이터
        timeout: 응답 대기 시간 (초)

    Returns:
        클라이언트로부터 받은 응답

    Raises:
        ValueError: 유저가 연결되지 않음
        TimeoutError: 응답 시간 초과

    Example:
        response = await sync_request(
            user_id=123,
            action="delete_chunks",
            data={"document_id": 456, "count": 10}
        )
    """
    manager = get_sync_manager()

    message = {
        "action": action,
        "data": data or {}
    }

    response = await manager.send_and_wait_response(
        user_id=user_id,
        message=message,
        timeout=timeout
    )

    return response


async def sync_notify(
    user_id: int,
    event: str,
    data: dict | None = None
) -> None:
    """
    클라이언트에게 일방적으로 알림 전송 (응답 기다리지 않음)

    Args:
        user_id: 대상 유저 ID
        event: 이벤트 타입 (예: "progress", "status_update")
        data: 추가 데이터

    Example:
        await sync_notify(
            user_id=123,
            event="progress",
            data={"current": 5, "total": 10}
        )
    """
    manager = get_sync_manager()

    message = {
        "type": "notification",
        "event": event,
        "data": data or {}
    }

    await manager.send_personal_json(message, user_id)
