from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Response
from maru_lang.enums.auth import UserRoleCode
from maru_lang.configs.system_config import get_system_config
from maru_lang.dependencies.auth import get_user

config = get_system_config()
from maru_lang.dependencies.email import get_email_service_dependency, EmailService
from maru_lang.schemas.auth import (
    VerifyCodeRequest,
    SignUpRequest,
    LogoutRequest,
)
from maru_lang.services.auth import (
    generate_token,
    verify_OTP,
    create_or_get_user,
    delete_token,
    generate_OTP,
)


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
        otp = await generate_OTP(request.email, email_service)

        # 이메일 서비스가 활성화된 경우에만 이메일 전송
        if email_service:
            success = email_service.send_otp(request.email, otp.code)
            if not success:
                # 이메일 전송 실패 시 DEFAULT_VALIDATION_CODE로 재생성
                await otp.delete()
                otp = await generate_OTP(request.email, None)

        return otp.email
    except Exception as e:
        print(e)
        raise HTTPException(
            status_code=400,
            detail="서버가 점검 중 입니다. 다시 시도해주세요.")


@router.post("/logout")
async def logout(
    request: LogoutRequest,
    response: Response,
    user=Depends(get_user)
) -> dict:
    try:
        await delete_token(user.id, request.device_id)
        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="strict"
        )
        return {"message": "Logged out successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify/code")
async def verify_code(
    response: Response,
    request: VerifyCodeRequest
):
    try:
        if not await verify_OTP(request.email, request.code):
            raise Exception("Invalid or expired code")
        user = await create_or_get_user(
            email=request.email,
            role=UserRoleCode.EDITOR.value
        )
        access_token, refresh_token = await generate_token(
            user.id,
            user.role_id,
            request.device_id)

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
