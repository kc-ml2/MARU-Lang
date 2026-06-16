from maru_lang.services.auth import (
    generate_token,
    generate_email_verification_code,
    verify_email_code,
    revoke_token,
    create_or_get_user,
    refresh_token_flow,
    generate_chat_token,
)
from maru_lang.services.team import get_or_create_team, add_member_to_team
from maru_lang.services.admin import (
    get_or_create_public_team,
    get_or_create_admin_user,
)
from maru_lang.schemas.auth import (
    VerifyCodeRequest,
    SignUpRequest,
    LogoutRequest,
    ChatTokenResponse,
)
from maru_lang.dependencies.email import get_email_service_dependency, EmailService
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response, Request, Query
from maru_lang.configs import get_config
from maru_lang.dependencies.auth import get_user

config = get_config()


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
    """Send OTP verification code to email."""
    if not config.auth.is_domain_allowed(request.email):
        raise HTTPException(
            status_code=403,
            detail="허용되지 않은 이메일 도메인입니다",
        )
    try:
        otp = await generate_email_verification_code(request.email, email_service)
        if email_service:
            success = email_service.send_otp(request.email, otp.code)
            if not success:
                await otp.delete()
                raise Exception("Failed to send verification email")
        return otp.email
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error: {str(e)}")


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    response: Response,
    user=Depends(get_user)
) -> dict:
    """Revoke tokens and clear refresh_token cookie."""
    try:
        await revoke_token(user.id, request.device_id)
        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="none",
            secure=True
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
    """Issue new access token using refresh token (rotation applied)."""
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
            samesite="none",
            secure=True
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
        samesite="none",
        max_age=config.auth.refresh_token_expire_minutes * 60,
    )

    return {"access_token": access_token}


@router.post("/verify/code")
async def verify_code(
    response: Response,
    request: VerifyCodeRequest
):
    """Verify OTP code and issue access/refresh tokens."""
    try:
        if not await verify_email_code(
            request.email, request.code
        ):
            raise Exception("Invalid or expired code")

        user = await create_or_get_user(request.email)

        # set up default team using domain
        # if example.co.kr -> example
        email_domain = request.email.split("@")[-1]
        domain_prefix = email_domain.split(".")[0]
        team, created = await get_or_create_team(
            name=domain_prefix,
            manager=user)

        # 자동생성 도메인 팀은 시스템 admin이 관리한다(public 팀과 동일 정책).
        # 먼저 로그인한 사람이 우연히 조직 팀의 admin이 되지 않도록, 일반 유저는
        # member로만 가입시키고 admin 권한은 시스템 admin에게 둔다.
        if created:
            admin_user = await get_or_create_admin_user()
            await add_member_to_team(
                team=team,
                user=admin_user,
                role="admin")

        await add_member_to_team(
            team=team,
            user=user)

        # Add user to public team
        public_team = await get_or_create_public_team()
        await add_member_to_team(
            team=public_team,
            user=user)

        access_token, refresh_token = await generate_token(
            user.id,
            request.device_id
        )

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite="none",
            max_age=config.auth.refresh_token_expire_minutes * 60
        )

        return access_token
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verify")
async def verify(_=Depends(get_user)):
    """Verify if access token is valid."""
    return {"message": "ok"}


@router.post("/chat-token", response_model=ChatTokenResponse)
async def get_chat_token(user=Depends(get_user)) -> ChatTokenResponse:
    """Issue one-time chat token for WebSocket connection."""
    token = await generate_chat_token(user.id)
    return ChatTokenResponse(chat_token=token)
