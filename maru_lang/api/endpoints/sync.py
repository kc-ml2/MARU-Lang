from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from maru_lang.dependencies.auth import get_user_from_websocket_token
from maru_lang.dependencies.sync import get_sync_manager

router = APIRouter(
    prefix="/sync",
    tags=["Sync"]
)


@router.websocket("/connect")
async def sync_endpoint(websocket: WebSocket):
    """
    Sync connection endpoint with Bearer token authentication.

    Usage for Electron (Node.js):
        const WebSocket = require('ws');
        const ws = new WebSocket(wsUrl, {
          headers: {
            'Authorization': `Bearer ${wsToken}`
          }
        });

    Note:
        - Authorization 헤더로만 인증합니다 (Electron/Node.js 환경)
        - 토큰이 만료되면 클라이언트에서 새 토큰으로 재연결해야 합니다.
        - Sync 연결은 refresh token 로직을 지원하지 않습니다.
    """
    user = None

    try:
        # Authorization 헤더 확인
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        auth_token = None

        if auth_header:
            if auth_header.startswith("Bearer "):
                auth_token = auth_header[7:]  # Remove "Bearer " prefix
            else:
                auth_token = auth_header

        if not auth_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication token")
            return

        # Authenticate user
        user = await get_user_from_websocket_token(auth_token)

        if not user:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
            return

        # Get sync manager instance
        manager = get_sync_manager()

        # Connection successful
        await manager.connect(user.id, websocket)
        print(f"✓ User {user.email} (ID: {user.id}) connected via sync")

        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": f"Welcome {user.email}!",
            "user_id": user.id
        })

        # Keep connection alive and handle messages
        while True:
            # 클라이언트로부터 메시지 수신
            message = await websocket.receive_json()

            # request_id가 있으면 응답 메시지임
            if "request_id" in message:
                # 대기 중인 Future를 완료시킴
                manager.handle_response(message["request_id"], message)
            else:
                # 일반 메시지는 큐에 추가
                await manager.add_message_to_queue(user.id, message)

    except WebSocketDisconnect:
        if user:
            manager = get_sync_manager()
            manager.disconnect(user.id)
            print(f"✓ User {user.email} (ID: {user.id}) disconnected")
    except Exception as e:
        print(f"❌ Sync connection error: {str(e)}")
        if user:
            manager = get_sync_manager()
            manager.disconnect(user.id)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason=str(e))
        except:
            pass
