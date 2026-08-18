"""认证相关 Pydantic schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class MfaVerifyRequest(BaseModel):
    """密码校验通过后的 MFA 验证。需在 step 1 的 Cookie 上下文中调用。"""
    code: str = Field(min_length=6, max_length=8)


class MfaBindRequest(BaseModel):
    """绑定 TOTP。step 1 返回的 secret 由前端暂存，回调时提交。"""
    secret: str
    code: str = Field(min_length=6, max_length=8)


class RecoveryLoginRequest(BaseModel):
    """使用恢复码登录。"""
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)
    recovery_code: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    """登录成功响应。"""
    session_id: str
    csrf_token: str
    username: str


class MfaRequiredResponse(BaseModel):
    """MFA 验证必要（密码正确但尚未完成 MFA）。"""
    require_mfa: bool = True
    step: str = "mfa_verify"


class MfaSetupRequiredResponse(BaseModel):
    """需要绑定 MFA（首次登录）。"""
    require_mfa_setup: bool = True
    totp_uri: str
    secret: str
    step: str = "mfa_setup"


class SessionInfoResponse(BaseModel):
    account_id: str
    username: str
    source_ip: str
    created_at: UTCDateTime | None
