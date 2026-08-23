"""管理账号服务测试（H03：初始化与最后超管保护）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.models.account_auth_state import ManagementAccountAuthState
from toolhive.models.account_role import AccountRole
from toolhive.models.management_account import ManagementAccount
from toolhive.models.management_audit_log import ManagementAuditLog
from toolhive.services.account_service import AccountService
from toolhive.services.audit_service import set_audit_actor


@pytest.fixture(autouse=True)
def _reset_actor() -> None:
    """每个测试前后清空当前操作人。"""
    set_audit_actor(None, None)
    yield
    set_audit_actor(None, None)


def _account(status: AccountStatus = AccountStatus.ENABLED) -> MagicMock:
    account = MagicMock()
    account.id = "acc-1"
    account.status = status
    account.auth_state = MagicMock()
    account.auth_state.login_failures = 0
    account.auth_state.locked_until = None
    account.auth_state.security_version = 0
    return account


def _offboarded_account() -> MagicMock:
    account = _account(status=AccountStatus.OFFBOARDED)
    account.row_version = 0
    return account


async def test_init_super_admin_creates_account_and_links_role():
    """初始化成功：创建账号并建立超管角色关联。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[0, MagicMock(id="role-1")])
    svc = AccountService(db, AdminSecuritySettings())

    account = await svc.init_super_admin("admin", "管理员", "StrongPass123!")

    assert isinstance(account, ManagementAccount)
    # CLI 初始化无登录操作人：create_by 留空，创建时间显式写入
    assert account.create_by is None
    assert account.create_time is not None
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, AccountRole) for item in added)
    # 初始化同时创建 1:1 认证状态行，初始密码不需要强制修改
    auth_rows = [
        item for item in added if isinstance(item, ManagementAccountAuthState)
    ]
    assert len(auth_rows) == 1
    assert auth_rows[0].must_change_password is False


async def test_create_account_creates_auth_state_row():
    """创建账号时同步创建 1:1 认证状态行（临时密码强制修改并设置过期时间）。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = AccountService(db, AdminSecuritySettings())
    set_audit_actor("acc-9", "operator")

    account, _ = await svc.create_account("alice", "Alice")

    added = [call.args[0] for call in db.add.call_args_list]
    auth_rows = [
        item for item in added if isinstance(item, ManagementAccountAuthState)
    ]
    assert len(auth_rows) == 1
    assert auth_rows[0].account_id == account.id
    assert auth_rows[0].must_change_password is True
    assert auth_rows[0].temp_password_expires_at is not None


async def test_create_account_sets_profile_fields():
    """创建账号时写入姓名/邮箱/手机号/部门/备注等资料字段。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = AccountService(db, AdminSecuritySettings())
    set_audit_actor("acc-9", "operator")

    account, _ = await svc.create_account(
        "alice",
        "Alice",
        external_user_id="EMP001",
        email="alice@example.com",
        mobile="13800000000",
        department="研发部",
        remark="备注",
    )

    assert account.account == "alice"
    assert account.real_name == "Alice"
    assert account.external_user_id == "EMP001"
    assert account.email == "alice@example.com"
    assert account.mobile == "13800000000"
    assert account.department == "研发部"
    assert account.remark == "备注"


async def test_init_super_admin_sets_real_name():
    """初始化超管时通过参数写入姓名。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[0, MagicMock(id="role-1")])
    svc = AccountService(db, AdminSecuritySettings())

    account = await svc.init_super_admin("admin", "管理员", "StrongPass123!")

    assert account.account == "admin"
    assert account.real_name == "管理员"


async def test_update_profile_updates_fields_with_audit():
    """编辑账号资料更新字段、自增版本号并写审计记录。"""
    account = _account()
    account.account = "alice"
    account.real_name = "Alice"
    account.email = None
    account.mobile = None
    account.department = None
    account.remark = None
    account.row_version = 3
    db = AsyncMock()
    db.add = MagicMock()
    svc = AccountService(db, AdminSecuritySettings())
    set_audit_actor("acc-9", "operator")

    updated = await svc.update_profile(
        account,
        real_name="Alice2",
        email="a@b.com",
        expected_row_version=3,
    )

    assert updated.real_name == "Alice2"
    assert updated.email == "a@b.com"
    assert updated.row_version == 4
    records = [
        call.args[0] for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementAuditLog)
    ]
    assert len(records) == 1
    assert records[0].action == "account.update"
    assert '"real_name": "Alice"' in records[0].before_summary
    assert '"real_name": "Alice2"' in records[0].after_summary


async def test_update_profile_row_version_conflict():
    """编辑资料时 row_version 不一致抛出乐观锁冲突。"""
    account = _account()
    account.row_version = 1
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with pytest.raises(ConflictError):
        await svc.update_profile(account, real_name="X", expected_row_version=0)


async def test_record_login_failure_updates_auth_state_only():
    """登录失败只更新认证状态行，不触碰账号主记录。"""
    fresh = MagicMock()
    fresh.status = AccountStatus.ENABLED
    fresh.auth_state = MagicMock()
    fresh.auth_state.login_failures = 0
    fresh.auth_state.locked_until = None

    new_db = AsyncMock()
    new_db.__aenter__ = AsyncMock(return_value=new_db)
    new_db.__aexit__ = AsyncMock(return_value=False)
    new_db.get = AsyncMock(return_value=fresh)
    new_db.commit = AsyncMock()

    svc = AccountService(AsyncMock(), AdminSecuritySettings())

    with patch(
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=new_db),
    ):
        await svc.record_login_failure(_account())

    assert fresh.auth_state.login_failures == 1
    assert fresh.status == AccountStatus.ENABLED
    assert fresh.auth_state.locked_until is None
    new_db.commit.assert_awaited_once()


async def test_record_login_failure_locks_at_threshold():
    """失败次数达到阈值时锁定账号并设置锁定到期时间。"""
    settings = AdminSecuritySettings()
    fresh = MagicMock()
    fresh.status = AccountStatus.ENABLED
    fresh.auth_state = MagicMock()
    fresh.auth_state.login_failures = settings.login_max_failures - 1
    fresh.auth_state.locked_until = None

    new_db = AsyncMock()
    new_db.__aenter__ = AsyncMock(return_value=new_db)
    new_db.__aexit__ = AsyncMock(return_value=False)
    new_db.get = AsyncMock(return_value=fresh)
    new_db.commit = AsyncMock()

    svc = AccountService(AsyncMock(), AdminSecuritySettings())

    with patch(
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=new_db),
    ):
        await svc.record_login_failure(_account())

    assert fresh.auth_state.login_failures == settings.login_max_failures
    assert fresh.status == AccountStatus.LOCKED
    assert fresh.auth_state.locked_until is not None


async def test_requires_new_reads_database_factory_at_call_time():
    """回归：requires_new 独立事务在调用时动态读取当前会话工厂，不依赖导入时机。"""
    fresh = MagicMock()
    fresh.status = AccountStatus.ENABLED
    fresh.auth_state = MagicMock()
    fresh.auth_state.login_failures = 0
    fresh.auth_state.locked_until = None

    new_db = AsyncMock()
    new_db.__aenter__ = AsyncMock(return_value=new_db)
    new_db.__aexit__ = AsyncMock(return_value=False)
    new_db.get = AsyncMock(return_value=fresh)
    new_db.commit = AsyncMock()

    svc = AccountService(AsyncMock(), AdminSecuritySettings())

    # 仅 patch database 模块的工厂（等价于 init_infrastructure 初始化后的运行时状态）
    with patch(
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=new_db),
    ):
        await svc.record_login_failure(_account())

    assert fresh.auth_state.login_failures == 1
    new_db.commit.assert_awaited_once()


def test_account_domain_tablenames_share_prefix():
    """账号域所有表统一使用 management_account_* 前缀。"""
    from toolhive.models.management_account import ManagementAccount
    from toolhive.models.password_history import PasswordHistory

    assert ManagementAccount.__tablename__ == "management_account"
    assert ManagementAccountAuthState.__tablename__ == "management_account_auth_state"
    assert AccountRole.__tablename__ == "management_account_role"
    assert PasswordHistory.__tablename__ == "management_account_password_history"


async def test_create_account_sets_audit_fields():
    """创建账号时写入创建时间与当前操作人 ID。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = AccountService(db, AdminSecuritySettings())
    set_audit_actor("acc-9", "operator")

    account, _ = await svc.create_account("alice", "Alice")

    assert account.create_time is not None
    assert account.create_by == "acc-9"


async def test_offboard_sets_offboarded_status():
    """离职处理后账号进入 offboarded 终态。"""
    db = AsyncMock()
    db.add = MagicMock()
    svc = AccountService(db, AdminSecuritySettings())
    account = _account()
    account.row_version = 0
    with (
        patch("toolhive.services.account_service.revoke_all_sessions", AsyncMock()) as revoke,
        patch("toolhive.services.account_service.RoleService") as role_cls,
    ):
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=False)
        await svc.offboard_account(account, operator_id="acc-2")

    assert account.status == AccountStatus.OFFBOARDED
    revoke.assert_awaited_once_with("acc-1")


async def test_enable_rejects_offboarded():
    """已离职账号不可启用。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with pytest.raises(ValidationError) as exc_info:
        await svc.enable_account(_offboarded_account())
    assert "已离职" in str(exc_info.value)


async def test_unlock_rejects_offboarded():
    """已离职账号不可解锁。"""
    db = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with pytest.raises(ValidationError) as exc_info:
        await svc.unlock_account(_offboarded_account())
    assert "已离职" in str(exc_info.value)


async def test_disable_rejects_offboarded():
    """已离职账号不可禁用。"""
    db = AsyncMock()
    audit_db = AsyncMock()
    audit_db.__aenter__ = AsyncMock(return_value=audit_db)
    audit_db.__aexit__ = AsyncMock(return_value=False)
    audit_db.add = MagicMock()
    audit_db.commit = AsyncMock()
    svc = AccountService(db, AdminSecuritySettings())

    with patch(
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=audit_db),
    ):
        with pytest.raises(ValidationError) as exc_info:
            await svc.disable_account(_offboarded_account(), operator_id="acc-2")
    assert "已离职" in str(exc_info.value)


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
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=audit_db),
    ):
        with pytest.raises(ValidationError):
            await svc.init_super_admin("admin", "管理员", "StrongPass123!")


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
        "toolhive.infrastructure.database.async_session_factory",
        MagicMock(return_value=audit_db),
    ):
        with pytest.raises(ValidationError):
            await svc.init_super_admin("admin", "管理员", "weak")


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
