from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from maru_lang.enums.auth import UserRoleCode
from maru_lang.core.relation_db.models.auth import User, UserRole
from maru_lang.utils.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login",
    auto_error=False
)


async def get_user(
    request: Request,
    token: str = Depends(oauth2_scheme)
) -> User:
    """Access token에서 유저 정보를 가져오는 함수. 만료 시 401 반환."""
    # SSE/EventSource는 커스텀 헤더를 지원하지 않으므로 쿼리 파라미터 지원
    if not token:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token not provided", "code": "TOKEN_MISSING"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Token expired", "code": "TOKEN_EXPIRED"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Invalid token", "code": "TOKEN_INVALID"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await User.get_or_none(id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "User not found", "code": "USER_NOT_FOUND"},
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
            UserRoleCode.ANONYMOUS,
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
