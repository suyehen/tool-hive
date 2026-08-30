"""管理侧操作级鉴权依赖测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from toolhive.api.admin.deps import _get_current_user, require_operation
from toolhive.core.enums import AccountStatus
from toolhive.core.operation_codes import OperationCode
from toolhive.services.audit_service import get_audit_trace, set_audit_trace


def _make_account(account_id: str = "acc-1") -> MagicMock:
    account = MagicMock()
    account.id = account_id
    account.auth_state = MagicMock()
    account.auth_state.security_version = "0"
    return account


async def test_require_operation_allows_with_permission():
    """账号拥有操作码时放行，并返回当前账号。"""
    db = AsyncMock()
    account = _make_account()
    with patch("toolhive.services.role_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.check_operation = AsyncMock(return_value=True)
        dep = require_operation(OperationCode.ADMIN_ACCOUNT_VIEW)
        result = await dep(request=MagicMock(), account=account, db=db)
    assert result is account
    role_svc.check_operation.assert_awaited_once_with(
        "acc-1",
        OperationCode.ADMIN_ACCOUNT_VIEW,
    )


async def test_require_operation_denies_without_permission():
    """账号缺少操作码时返回 403。"""
    db = AsyncMock()
    account = _make_account()
    with patch("toolhive.services.role_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.check_operation = AsyncMock(return_value=False)
        dep = require_operation(OperationCode.ROLE_MANAGE)
        with pytest.raises(HTTPException) as exc_info:
            await dep(request=MagicMock(), account=account, db=db)
    assert exc_info.value.status_code == 403
    assert "缺少操作项" in str(exc_info.value.detail)


async def test_require_operation_caller_policy():
    """调用系统运行策略操作码由 require_operation 统一放行/拒绝。"""
    db = AsyncMock()
    account = _make_account()
    with patch("toolhive.services.role_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.check_operation = AsyncMock(return_value=True)
        dep = require_operation(OperationCode.CALLER_SYSTEM_POLICY)
        result = await dep(request=MagicMock(), account=account, db=db)
    assert result is account
    role_svc.check_operation.assert_awaited_once_with(
        "acc-1",
        OperationCode.CALLER_SYSTEM_POLICY,
    )


async def test_require_operation_captures_trace_header():
    """require_operation 捕获 X-ToolHive-Trace-Id 写入审计上下文。"""
    set_audit_trace(None)
    db = AsyncMock()
    account = _make_account()
    request = MagicMock()
    request.headers.get = MagicMock(return_value="trace-abc")
    with patch("toolhive.services.role_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.check_operation = AsyncMock(return_value=True)
        dep = require_operation(OperationCode.ADMIN_ACCOUNT_VIEW)
        await dep(request=request, account=account, db=db)
    assert get_audit_trace() == "trace-abc"
    set_audit_trace(None)


async def test_get_current_user_requires_session():
    """无有效会话时返回 401。"""
    request = MagicMock()
    request.state.session = None
    with pytest.raises(HTTPException) as exc_info:
        await _get_current_user(
            request=request,
            db=AsyncMock(),
            admin_security=MagicMock(),
        )
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_security_version_mismatch():
    """会话 security_version 与账号不一致时要求重新登录（401）。"""
    request = MagicMock()
    request.state.session = MagicMock()
    request.state.session.account_id = "acc-1"
    request.state.session.security_version = "0"

    account = _make_account()
    account.auth_state.security_version = "1"

    with patch("toolhive.services.account_service.AccountService") as acct_cls:
        acct_svc = acct_cls.return_value
        acct_svc.get_by_id = AsyncMock(return_value=account)
        with pytest.raises(HTTPException) as exc_info:
            await _get_current_user(
                request=request,
                db=AsyncMock(),
                admin_security=MagicMock(),
            )
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_locked_account():
    """锁定账号即使 security_version 一致也拒绝访问（401）。"""
    request = MagicMock()
    request.state.session = MagicMock()
    request.state.session.account_id = "acc-1"
    request.state.session.security_version = "0"

    account = _make_account()
    account.status = AccountStatus.LOCKED
    account.is_active.return_value = False

    with patch("toolhive.services.account_service.AccountService") as acct_cls:
        acct_svc = acct_cls.return_value
        acct_svc.get_by_id = AsyncMock(return_value=account)
        with pytest.raises(HTTPException) as exc_info:
            await _get_current_user(
                request=request,
                db=AsyncMock(),
                admin_security=MagicMock(),
            )
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_disabled_account():
    """禁用账号即使 security_version 一致也拒绝访问（401）。"""
    request = MagicMock()
    request.state.session = MagicMock()
    request.state.session.account_id = "acc-1"
    request.state.session.security_version = "0"

    account = _make_account()
    account.status = AccountStatus.DISABLED
    account.is_active.return_value = False

    with patch("toolhive.services.account_service.AccountService") as acct_cls:
        acct_svc = acct_cls.return_value
        acct_svc.get_by_id = AsyncMock(return_value=account)
        with pytest.raises(HTTPException) as exc_info:
            await _get_current_user(
                request=request,
                db=AsyncMock(),
                admin_security=MagicMock(),
            )
    assert exc_info.value.status_code == 401


async def test_get_current_user_blocks_non_auth_when_must_change_password():
    """未修改临时密码前，非 auth 接口返回 403。"""
    request = MagicMock()
    request.url.path = "/accounts"
    request.state.session = MagicMock()
    request.state.session.account_id = "acc-1"
    request.state.session.security_version = "0"

    account = _make_account()
    account.is_active.return_value = True
    account.auth_state.must_change_password = True

    with patch("toolhive.services.account_service.AccountService") as acct_cls:
        acct_svc = acct_cls.return_value
        acct_svc.get_by_id = AsyncMock(return_value=account)
        with pytest.raises(HTTPException) as exc_info:
            await _get_current_user(
                request=request,
                db=AsyncMock(),
                admin_security=MagicMock(),
            )
    assert exc_info.value.status_code == 403


async def test_get_current_user_allows_auth_when_must_change_password():
    """未修改临时密码前，auth 接口（含挂载前缀）放行。"""
    request = MagicMock()
    request.url.path = "/api/admin/auth/me"
    request.state.session = MagicMock()
    request.state.session.account_id = "acc-1"
    request.state.session.security_version = "0"

    account = _make_account()
    account.is_active.return_value = True
    account.auth_state.must_change_password = True

    with patch("toolhive.services.account_service.AccountService") as acct_cls:
        acct_svc = acct_cls.return_value
        acct_svc.get_by_id = AsyncMock(return_value=account)
        result = await _get_current_user(
            request=request,
            db=AsyncMock(),
            admin_security=MagicMock(),
        )
    assert result is account
