# 시크릿 키, 알고리즘, 토큰 만료 시간 등을 settings에서 관리
from fastapi import Depends, HTTPException, status, Request, Body
from fastapi.security import OAuth2PasswordBearer
from maru_lang.enums.auth import UserRoleCode
from maru_lang.core.relation_db.models.auth import User, UserRole, RefreshToken
from maru_lang.utils.security import decode_token
from maru_lang.services.auth import refresh_token_flow

# 1) OAuth2 스키마 설정
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/editor/login",
    auto_error=False)


async def get_user(
    request: Request,
    token: str = Depends(oauth2_scheme)
) -> User:
    """토큰에서 유저 ID 등을 추출하여 실제 유저 정보를 가져오는 함수"""
    # device-id는 헤더 또는 쿼리스트링(device-id)로 전달 받을 수 있도록 확장
    device_id_in_header = request.headers.get("device-id") or request.query_params.get("device-id")

    # 토큰은 헤더(Authorization) 또는 쿼리 파라미터(token)에서 받을 수 있음
    # SSE/EventSource는 커스텀 헤더를 지원하지 않으므로 쿼리 파라미터 지원 필요
    if not token:
        token = request.query_params.get("token")

    payload = decode_token(token) if token else None

    if payload is None:
        # AccessToken 만료 → refresh_token 꺼내기
        refresh_token = request.cookies.get("refresh_token")
        if not refresh_token:
            # 임시로 만약 서버를 재시작 했을때를 대비해서
            # 보안적으로 안전하지 않다 salt를 해야할수도
            refresh_token_object = await RefreshToken.filter(
                device_id=device_id_in_header
            ).order_by(
                "-created_at"
            ).first()
            if refresh_token_object:
                refresh_token = refresh_token_object.refresh_token
                try:
                    decode_token(refresh_token)
                except Exception:
                    raise HTTPException(
                        status_code=401, detail="Invalid refresh token")

        if refresh_token:
            new_access_token = await refresh_token_flow(refresh_token, device_id_in_header)
            if new_access_token:
                # 새 토큰으로 재인증 시도
                payload = decode_token(new_access_token)
                # 🔥 새 AccessToken을 응답 헤더에 추가 (선택)
                request.state.new_access_token = new_access_token

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: no user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.get_or_none(id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def get_user_with_role(
    required_role: UserRoleCode,
):
    async def dependency(
        user: User = Depends(get_user)
    ):
        # 역할 우선순위 (낮은 권한부터 높은 권한 순)
        ROLE_HIERARCHY = [
            UserRoleCode.EDITOR,
            UserRoleCode.ADMIN,
        ]
        # get user role
        user_role = await UserRole.get_or_none(
            id=user.role_id
        )

        if not user_role:
            raise HTTPException(status_code=401, detail="Unauthorized role")

        try:
            user_index = ROLE_HIERARCHY.index(UserRoleCode(user_role.name))
            required_index = ROLE_HIERARCHY.index(required_role)
        except ValueError:
            raise HTTPException(status_code=401, detail="Invalid role")

        if user_index < required_index:
            raise HTTPException(status_code=403, detail="Permission denied")

        return user

    return dependency


async def get_user_from_websocket_token(token: str) -> User | None:
    """
    WebSocket용 토큰 검증 및 유저 조회

    Note: WebSocket에서는 refresh token 로직을 사용하지 않습니다.
    클라이언트에서 새 access token을 받아서 재연결해야 합니다.
    """
    payload = decode_token(token) if token else None

    if payload is None:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    user = await User.get_or_none(id=user_id)
    return user
