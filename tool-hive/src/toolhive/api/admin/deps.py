"""管理侧 API 公共依赖：会话鉴权与操作级鉴权。

业务模块（Controller）通过依赖获取当前管理账号，并通过
``require_operation`` 声明接口所需的管理操作码；后端独立完成操作码校验，
不能只依赖前端隐藏按钮（默认拒绝）。
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.deps import get_admin_security
from toolhive.config import AdminSecuritySettings
from toolhive.core.exceptions import ToolHiveError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.audit_service import set_audit_actor, set_audit_trace


async def _get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
):
    """依赖注入：获取当前管理账号（要求会话有效）。"""
    session = getattr(request.state, "session", None)
    if session is None:
        raise HTTPException(status_code=401, detail="未认证")

    from toolhive.services.account_service import AccountService
    svc = AccountService(db, admin_security)
    try:
        account = await svc.get_by_id(session.account_id)
    except ToolHiveError:
        raise HTTPException(status_code=401, detail="未认证")
    # security_version 不一致 → 会话已失效，要求重新登录
    if str(session.security_version) != str(account.auth_state.security_version):
        raise HTTPException(status_code=401, detail="会话已失效，请重新登录")
    # 账号不可用（禁用/锁定/离职）→ 实时拒绝，前端收到 401 后跳转登录
    if not account.is_active():
        raise HTTPException(status_code=401, detail="账号不可用，请重新登录")
    # 强制改密：未修改临时密码前，只允许访问 auth 相关接口
    if account.auth_state.must_change_password:
        path = request.url.path.removeprefix("/api/admin")
        if not path.startswith("/auth/"):
            raise HTTPException(status_code=403, detail="请先修改密码")
    return account


def require_operation(code: OperationCode):
    """操作级鉴权依赖：已登录且账号拥有指定操作码，否则返回 403。

    权限实时计算（不缓存、不保存授权快照），超级管理员自动拥有全部有效
    操作项；未登录或会话失效仍由 ``_get_current_user`` 返回 401。
    """

    async def _dependency(
        request: Request,
        account=Depends(_get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        # 捕获管理请求透传 Trace ID（非法忽略），供审计记录关联
        set_audit_trace(request.headers.get("X-ToolHive-Trace-Id"))
        # 记录当前请求操作人，供 Service 层审计埋点读取
        set_audit_actor(account.id, account.account)
        from toolhive.services.role_service import RoleService
        svc = RoleService(db)
        if not await svc.check_operation(account.id, code):
            raise HTTPException(status_code=403, detail=f"缺少操作项: {code}")
        return account

    return _dependency
