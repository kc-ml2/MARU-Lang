from pydantic import BaseModel, Field, field_validator
from typing import Optional


def _validate_email(value: str) -> str:
    """Reject structurally invalid addresses before they reach auth logic.

    `email` is a plain `str` (not `EmailStr`, to avoid the email-validator
    dependency), so without this an address like "a@evil.com@allowed.com"
    would slip through domain allow-listing. Require exactly one "@" with
    non-empty local and domain parts; normalize surrounding whitespace.
    """
    value = (value or "").strip()
    parts = value.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1] or "." not in parts[1]:
        raise ValueError("유효하지 않은 이메일 주소입니다")
    return value


class SignUpRequest(BaseModel):
    email: str

    _normalize_email = field_validator("email")(_validate_email)


class LogoutRequest(BaseModel):
    device_id: str


class VerifyCodeRequest(BaseModel):
    device_id: str
    email: str
    code: str

    _normalize_email = field_validator("email")(_validate_email)


class UserResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None

    class Config:
        from_attributes = True


class UpdateMeRequest(BaseModel):
    """본인 표시명(닉네임) 변경 요청."""
    name: str = Field(..., min_length=1, description="전역 표시명(닉네임)")


class ChatTokenResponse(BaseModel):
    chat_token: str
