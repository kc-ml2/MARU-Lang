from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DeviceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
VerificationCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class SignUpRequest(BaseModel):
    email: EmailStr


class LogoutRequest(BaseModel):
    device_id: DeviceId


class VerifyCodeRequest(BaseModel):
    device_id: DeviceId
    email: EmailStr
    code: VerificationCode


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str | None = None


class UpdateMeRequest(BaseModel):
    name: DisplayName = Field(description="전역 표시명(닉네임)")
