import asyncio
import uuid
from typing import Dict, Any
from fastapi import WebSocket
from asyncio import Queue, Future


class SyncConnectionManager:
    """Sync connection manager for handling multiple client connections via WebSocket"""

    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        # 각 유저별 수신 메시지 큐
        self.message_queues: Dict[int, Queue] = {}
        # request_id -> Future 매핑 (요청-응답 패턴용)
        self.pending_requests: Dict[str, Future] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """Accept and store a sync connection for a user"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        # 유저별 메시지 큐 생성
        self.message_queues[user_id] = Queue()

    def disconnect(self, user_id: int):
        """Remove a user's sync connection"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if user_id in self.message_queues:
            del self.message_queues[user_id]

    async def send_personal_message(self, message: str, user_id: int):
        """Send a message to a specific user"""
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_text(message)

    async def send_personal_json(self, data: dict, user_id: int):
        """Send JSON data to a specific user"""
        if user_id in self.active_connections:
            await self.active_connections[user_id].send_json(data)

    async def broadcast(self, message: str):
        """Broadcast a message to all connected users"""
        for connection in self.active_connections.values():
            await connection.send_text(message)

    async def broadcast_json(self, data: dict):
        """Broadcast JSON data to all connected users"""
        for connection in self.active_connections.values():
            await connection.send_json(data)

    def get_connection(self, user_id: int) -> WebSocket | None:
        """Get a specific user's sync connection"""
        return self.active_connections.get(user_id)

    def is_connected(self, user_id: int) -> bool:
        """Check if a user is currently connected"""
        return user_id in self.active_connections

    def get_connected_user_count(self) -> int:
        """Get the number of connected users"""
        return len(self.active_connections)

    def get_connected_user_ids(self) -> list[int]:
        """Get list of all connected user IDs"""
        return list(self.active_connections.keys())

    async def add_message_to_queue(self, user_id: int, message: Any):
        """수신한 메시지를 유저의 큐에 추가"""
        if user_id in self.message_queues:
            await self.message_queues[user_id].put(message)

    async def get_message_from_queue(self, user_id: int, timeout: float | None = None) -> Any:
        """유저의 큐에서 메시지를 가져옴 (blocking)"""
        if user_id not in self.message_queues:
            raise ValueError(f"User {user_id} is not connected")

        try:
            if timeout:
                return await asyncio.wait_for(
                    self.message_queues[user_id].get(),
                    timeout=timeout
                )
            else:
                return await self.message_queues[user_id].get()
        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for message from user {user_id}")

    async def send_and_wait_response(
        self,
        user_id: int,
        message: dict,
        timeout: float = 30.0
    ) -> Any:
        """
        메시지를 보내고 응답을 기다림 (요청-응답 패턴)

        Args:
            user_id: 대상 유저 ID
            message: 보낼 메시지 (dict)
            timeout: 응답 대기 시간 (초)

        Returns:
            응답 메시지

        Raises:
            TimeoutError: 응답 시간 초과
            ValueError: 유저가 연결되지 않음
        """
        if user_id not in self.active_connections:
            raise ValueError(f"User {user_id} is not connected")

        # 고유한 request_id 생성
        request_id = str(uuid.uuid4())
        message["request_id"] = request_id

        # Future 생성 및 등록
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future

        try:
            # 메시지 전송
            await self.send_personal_json(message, user_id)
            # 응답 대기
            response = await asyncio.wait_for(future, timeout=timeout)
            return response

        except asyncio.TimeoutError:
            raise TimeoutError(f"Timeout waiting for response from user {user_id}")
        finally:
            # 완료된 request 정리
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def handle_response(self, request_id: str, response: Any):
        """
        클라이언트로부터 온 응답을 처리하여 대기 중인 Future를 완료시킴

        Args:
            request_id: 요청 ID
            response: 응답 데이터
        """
        if request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(response)
