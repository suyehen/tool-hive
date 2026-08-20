"""管理账号服务测试（H03：初始化与最后超管保护）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import ValidationError
from toolhive.models.account_role import AccountRole
from toolhive.models.management_account import ManagementAccount
from toolhive.services.account_service import AccountService


def _account(status: AccountStatus = AccountStatus.ENABLED) -> MagicMock:
    account = MagicMock()
    account.id = "acc-1"
    account.status = status
    return account


async def test_init_super_admin_creates_account_and_links_role():
    """初始化成功：创建账号并建立超管角色关联。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[0, MagicMock(id="role-1")])
    svc = AccountService(db, AdminSecuritySettings())

    account = await svc.init_super_admin("admin", "StrongPass123!")

    assert isinstance(account, ManagementAccount)
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, AccountRole) for item in added)


async def test_init_super_admin_rejects_when_accounts_exist():
    """已存在账号时拒绝重复初始化。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)
    audit_db = AsyncMock()
    audit_db.__aenter__ = AsyncMock(return_value=audit_db)
    audit_db.__aexit__ = AsyncMock(return_value=False)
    audit_db.add = MagicMock()
    audit_db.commit = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with patch(
        "toolhive.services.audit_service.async_session_factory",
        MagicMock(return_value=audit_db),
    ):
        with pytest.raises(ValidationError):
            await svc.init_super_admin("admin", "StrongPass123!")


async def test_init_super_admin_rejects_weak_password():
    """初始密码不满足强度要求时拒绝。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    audit_db = AsyncMock()
    audit_db.__aenter__ = AsyncMock(return_value=audit_db)
    audit_db.__aexit__ = AsyncMock(return_value=False)
    audit_db.add = MagicMock()
    audit_db.commit = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with patch(
        "toolhive.services.audit_service.async_session_factory",
        MagicMock(return_value=audit_db),
    ):
        with pytest.raises(ValidationError):
            await svc.init_super_admin("admin", "weak")


async def test_has_any_account():
    """初始化状态查询。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())
    db.scalar = AsyncMock(return_value=0)
    assert await svc.has_any_account() is False
    db.scalar = AsyncMock(return_value=1)
    assert await svc.has_any_account() is True


async def test_check_last_super_admin_blocks_last_enabled():
    """最后一个启用状态的超管不允许停用/离职。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())
    with patch("toolhive.services.account_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=True)
        role_svc.count_enabled_super_admins = AsyncMock(return_value=1)
        with pytest.raises(ValidationError):
            await svc._check_last_super_admin(_account())


async def test_check_last_super_admin_allows_when_more_than_one():
    """存在多个启用超管时允许停用。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())
    with patch("toolhive.services.account_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=True)
        role_svc.count_enabled_super_admins = AsyncMock(return_value=2)
        await svc._check_last_super_admin(_account())


async def test_check_last_super_admin_ignores_non_super_admin():
    """非超管账号不受最后超管保护限制。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())
    with patch("toolhive.services.account_service.RoleService") as role_cls:
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=False)
        await svc._check_last_super_admin(_account())
