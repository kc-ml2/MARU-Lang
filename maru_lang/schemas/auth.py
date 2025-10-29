from pydantic import BaseModel


class SignUpRequest(BaseModel):
    email: str


class LogoutRequest(BaseModel):
    device_id: str


class VerifyCodeRequest(BaseModel):
    device_id: str
    email: str
    code: str
