"""认证相关 Pydantic schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    captcha_id: str = Field(min_length=1, max_length=128)
    captcha_code: str = Field(min_length=1, max_length=16)


class CaptchaChallengeResponse(BaseModel):
    """图形验证码挑战：标识、图片（base64 data URI）与有效期。"""

    captcha_id: str
    image: str
    expires_in_seconds: int


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """登录成功响应。"""
    session_id: str
    csrf_token: str
    account: str
    must_change_password: bool


class SessionInfoResponse(BaseModel):
    account_id: str
    account: str
    source_ip: str
    created_at: UTCDateTime | None
