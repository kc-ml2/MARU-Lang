from maru_lang.services.auth import (
    generate_token,
    get_user_groups,
    generate_email_verification_code,
    verify_email_code,
    revoke_token,
    create_or_get_user,
    refresh_token_flow,
)
from maru_lang.schemas.auth import (
    VerifyCodeRequest,
    SignUpRequest,
    LogoutRequest,
    UserGroupsResponse,
    UserGroupResponse,
)
from maru_lang.dependencies.email import get_email_service_dependency, EmailService
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response, Request, Query
from maru_lang.enums.auth import UserRoleCode
from maru_lang.configs.system_config import get_system_config
from maru_lang.dependencies.auth import get_user

config = get_system_config()


router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)


@router.post("/login")
async def login(
    request: SignUpRequest,
    email_service: Optional[EmailService] = Depends(
        get_email_service_dependency)
) -> str:
    try:
        # TODO Email validation
        otp = await generate_email_verification_code(request.email, email_service)

        # 이메일 서비스가 활성화된 경우에만 이메일 전송
        if email_service:
            success = email_service.send_otp(request.email, otp.code)
            if not success:
                # 이메일 전송 실패 시 DEFAULT_VALIDATION_CODE로 재생성
                await otp.delete()
                raise Exception("Failed to send verification email")
        return otp.email
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"서버가 점검 중 입니다. 다시 시도해주세요.\nError: {str(e)}")


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    response: Response,
    user=Depends(get_user)
) -> dict:
    try:
        await revoke_token(user.id, request.device_id)
        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="strict"
        )
        return {"message": "Logged out successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    device_id: str = Query(...),
):
    """Refresh token을 사용하여 새로운 토큰 발급"""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=401,
            detail="Refresh token not found"
        )

    result = await refresh_token_flow(refresh_token, device_id)
    if not result:
        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="strict"
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    access_token, new_refresh_token = result

    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=config.auth.refresh_token_expire_minutes * 60
    )

    return {"access_token": access_token}


@router.post("/verify/code")
async def verify_code(
    response: Response,
    request: VerifyCodeRequest
):
    try:
        if not await verify_email_code(
            request.email, request.code
        ):
            raise Exception("Invalid or expired code")

        user = await create_or_get_user(request.email)

        access_token, refresh_token = await generate_token(
            user.id,
            request.device_id
        )

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=config.auth.refresh_token_expire_minutes * 60
        )

        return access_token
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verify")
async def verify(_=Depends(get_user)):
    return {"message": "ok"}


@router.get("/user/groups", response_model=UserGroupsResponse)
async def get_current_user_groups(
    user=Depends(get_user)
):
    """
    Get user groups that the authenticated user belongs to.

    Returns:
        UserGroupsResponse: List of user groups with total count
    """
    try:
        # Get user groups using service function
        groups = await get_user_groups(user)

        # Convert to response format
        group_responses = [
            UserGroupResponse(
                id=group.id,
                name=group.name
            )
            for group in groups
        ]
        return UserGroupsResponse(
            groups=group_responses,
            total=len(group_responses)
        )

    except Exception as e:
        print(f"❌ Error fetching user groups: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
