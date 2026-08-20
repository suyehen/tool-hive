"""管理侧认证 API 路由。"""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.auth.schemas import (
    CaptchaChallengeResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    SessionInfoResponse,
)
from toolhive.api.admin.deps import _get_current_user
from toolhive.api.deps import get_admin_security
from toolhive.config import AdminSecuritySettings
from toolhive.core.exceptions import (
    AuthenticationError,
    ValidationError,
)
from toolhive.infrastructure.database import get_db
from toolhive.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])

# ── Cookie 设置工具函数 ──

SESSION_COOKIE = "toolhive_session"


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=8 * 3600,
        path="/api/admin",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/api/admin",
    )


# ── 端点 ──


@router.post("/captcha/challenge", response_model=CaptchaChallengeResponse)
async def captcha_challenge():
    """申请图形验证码挑战（公开接口，无需登录）。

    返回短期有效的验证码标识、PNG 图片（base64 data URI）与有效期；
    登录时需携带该标识与用户输入的验证码内容。
    """
    from toolhive.services.security.captcha import create_captcha_challenge
    return await create_captcha_challenge()


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
):
    """图形验证码 + 账号密码登录，成功直接创建管理会话。"""
    svc = AuthService(db, admin_security)
    try:
        source_ip = request.headers.get(
            "X-Forwarded-For",
            request.client.host if request.client else "unknown",
        )
        result = await svc.login_password(
            username=body.username,
            password=body.password,
            source_ip=source_ip,
            captcha_id=body.captcha_id,
            captcha_code=body.captcha_code,
        )
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))

    _set_session_cookie(response, result.session_id)
    return LoginResponse(
        session_id=result.session_id,
        csrf_token=result.csrf_token,
        username=result.account.username,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
):
    """登出，服务端删除会话。"""
    session_id = request.cookies.get(SESSION_COOKIE)
    if session_id:
        svc = AuthService(db, admin_security)
        await svc.logout(session_id)
    _clear_session_cookie(response)
    return {"detail": "已登出"}


@router.get("/session", response_model=SessionInfoResponse)
async def get_session_info(
    request: Request,
    account=Depends(_get_current_user),
):
    """查看当前会话信息。"""
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="未认证")
    from datetime import datetime

    created_at_dt = None
    if session.created_at:
        try:
            created_at_dt = datetime.fromtimestamp(
                int(session.created_at), tz=UTC,
            )
        except (ValueError, OverflowError):
            created_at_dt = None
    return SessionInfoResponse(
        account_id=session.account_id,
        username=session.username,
        source_ip=session.source_ip,
        created_at=created_at_dt,
    )


@router.get("/me")
async def get_me(
    account=Depends(_get_current_user),
):
    """获取当前账号信息（权限实时生效，前端据此刷新展示）。"""
    return {
        "account_id": account.id,
        "username": account.username,
        "external_user_id": account.external_user_id,
        "status": account.status,
    }


@router.get("/me/operation-items")
async def get_my_operation_items(
    db: AsyncSession = Depends(get_db),
    account=Depends(_get_current_user),
):
    """获取当前账号的有效管理操作项（实时计算，超管自动全量）。"""
    from toolhive.services.role_service import RoleService
    svc = RoleService(db)
    ops = await svc.get_effective_operations(account.id)
    return {"operation_items": sorted(str(o) for o in ops)}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    account=Depends(_get_current_user),
):
    """修改自己的密码，重新生成会话 ID。"""
    svc = AuthService(db, admin_security)
    try:
        await svc.account_svc.update_password(account, body.old_password, body.new_password)
    except (AuthenticationError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 会话 ID 轮转（防会话固定）
    old_session_id = request.cookies.get(SESSION_COOKIE)
    if old_session_id:
        from toolhive.services.security.session import rotate_session_id
        await svc.logout(old_session_id)
        await rotate_session_id(old_session_id)  # 这里需要重新创建
        # 简化：直接重新创建会话
        from toolhive.services.security.session import create_session
        source_ip = request.headers.get(
            "X-Forwarded-For",
            request.client.host if request.client else "unknown",
        )
        new_sid = await create_session(
            account_id=account.id,
            username=account.username,
            security_version=account.security_version,
            source_ip=source_ip,
        )
        _set_session_cookie(response, new_sid)

    return {"detail": "密码已修改"}


@router.get("/csrf-token")
async def get_csrf_token(
    request: Request,
    account=Depends(_get_current_user),
):
    """获取当前会话的 CSRF Token（前端首次加载时调用）。"""
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="未认证")
    from toolhive.services.security.csrf import generate_csrf_token
    token = generate_csrf_token(session.session_id)
    return {"csrf_token": token}
