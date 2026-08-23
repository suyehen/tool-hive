"""基础管理审计测试（H07）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus, CallerSystemStatus
from toolhive.core.exceptions import ValidationError
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.models.management_audit_log import ManagementAuditLog
from toolhive.models.management_role import ManagementRole
from toolhive.services.account_service import AccountService
from toolhive.services.audit_service import (
    AuditService,
    sanitize_summary,
    set_audit_actor,
)
from toolhive.services.caller_system_service import CallerSystemService
from toolhive.services.role_service import RoleService


def _account(status: AccountStatus = AccountStatus.ENABLED) -> MagicMock:
    account = MagicMock()
    account.id = "acc-1"
    account.account = "admin"
    account.status = status
    account.auth_state = MagicMock()
    account.auth_state.security_version = 0
    account.auth_state.login_failures = 0
    return account


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


def _audit_records(db) -> list[ManagementAuditLog]:
    return [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementAuditLog)
    ]


@pytest.fixture(autouse=True)
def _reset_actor() -> None:
    """每个测试前后清空当前操作人。"""
    set_audit_actor(None, None)
    yield
    set_audit_actor(None, None)


def test_sanitize_summary_masks_sensitive_fields() -> None:
    """密码、公钥等敏感字段在摘要中脱敏。"""
    out = sanitize_summary({
        "account": "admin",
        "password": "p@ss",
        "nested": {"public_key": "abc"},
        "codes": ["x", "y"],
    })
    assert out["password"] == "***"
    assert out["nested"]["public_key"] == "***"
    assert out["account"] == "admin"
    assert out["codes"] == ["x", "y"]


def test_add_record_writes_to_current_session_with_actor() -> None:
    """成功审计写入当前会话，并自动带上操作人与脱敏摘要。"""
    db = AsyncMock()
    db.add = MagicMock()
    set_audit_actor("acc-9", "operator")

    AuditService(db).add_record(
        action="account.disable",
        object_type="account",
        object_id="acc-1",
        after_summary={"status": "disabled", "new_password": "secret"},
    )

    db.add.assert_called_once()
    record = db.add.call_args.args[0]
    assert isinstance(record, ManagementAuditLog)
    assert record.actor_account_id == "acc-9"
    assert record.actor_account_name == "operator"
    assert record.action == "account.disable"
    assert record.result == "success"
    assert '"new_password": "***"' in record.after_summary


async def test_record_standalone_commits_independently() -> None:
    """失败审计使用独立事务立即提交。"""
    db = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    db.add = MagicMock()
    db.commit = AsyncMock()
    factory = MagicMock(return_value=db)
    with patch("toolhive.infrastructure.database.async_session_factory", factory):
        await AuditService.record_standalone(
            action="admin.init",
            object_type="account",
            result="failure",
            reason="已存在管理账号",
        )

    db.add.assert_called_once()
    record = db.add.call_args.args[0]
    assert record.action == "admin.init"
    assert record.result == "failure"
    assert record.reason == "已存在管理账号"
    db.commit.assert_awaited_once()


async def test_init_super_admin_success_records_audit_in_tx() -> None:
    """初始化成功时审计记录随业务事务一起提交。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[0, MagicMock(id="role-1")])
    svc = AccountService(db, AdminSecuritySettings())

    await svc.init_super_admin("admin", "管理员", "StrongPass123!")

    records = _audit_records(db)
    assert len(records) == 1
    assert records[0].action == "admin.init"
    assert records[0].result == "success"
    assert records[0].actor_account_name == "admin"


async def test_init_super_admin_failure_records_standalone() -> None:
    """初始化失败时失败审计走独立事务，不被业务回滚吞掉。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)
    audit_db = AsyncMock()
    audit_db.__aenter__ = AsyncMock(return_value=audit_db)
    audit_db.__aexit__ = AsyncMock(return_value=False)
    audit_db.add = MagicMock()
    audit_db.commit = AsyncMock()
    factory = MagicMock(return_value=audit_db)
    svc = AccountService(db, AdminSecuritySettings())

    with patch("toolhive.infrastructure.database.async_session_factory", factory):
        with pytest.raises(ValidationError):
            await svc.init_super_admin("admin", "管理员", "WeakPass!")

    audit_db.add.assert_called_once()
    record = audit_db.add.call_args.args[0]
    assert record.action == "admin.init"
    assert record.result == "failure"
    audit_db.commit.assert_awaited_once()


async def test_disable_last_super_admin_records_failure() -> None:
    """最后超管保护失败时记录失败审计。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_account())
    audit_db = AsyncMock()
    audit_db.__aenter__ = AsyncMock(return_value=audit_db)
    audit_db.__aexit__ = AsyncMock(return_value=False)
    audit_db.add = MagicMock()
    audit_db.commit = AsyncMock()
    factory = MagicMock(return_value=audit_db)
    svc = AccountService(db, AdminSecuritySettings())

    with patch("toolhive.infrastructure.database.async_session_factory", factory), patch(
        "toolhive.services.account_service.RoleService",
    ) as role_cls:
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=True)
        role_svc.count_enabled_super_admins = AsyncMock(return_value=1)
        with pytest.raises(ValidationError):
            await svc.disable_account(_account(), operator_id="acc-2")

    record = audit_db.add.call_args.args[0]
    assert record.action == "account.disable"
    assert record.result == "failure"
    audit_db.commit.assert_awaited_once()


async def test_role_create_records_audit() -> None:
    """角色创建写入审计记录。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)
    set_audit_actor("acc-9", "operator")

    role = await svc.create_role("ops", "ops")

    records = _audit_records(db)
    assert len(records) == 1
    assert records[0].action == "role.create"
    assert records[0].result == "success"
    # 创建时写入创建时间与当前操作人 ID
    assert role.create_time is not None
    assert role.create_by == "acc-9"


async def test_role_update_sets_audit_fields() -> None:
    """角色更新写入修改时间与当前操作人 ID。"""
    db = AsyncMock()
    role = ManagementRole(name="ops")
    role.row_version = 0
    db.get = AsyncMock(return_value=role)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)
    set_audit_actor("acc-9", "operator")

    updated = await svc.update_role("role-1", name="ops2")

    assert updated.update_time is not None
    assert updated.update_by == "acc-9"


async def test_caller_system_enable_records_audit() -> None:
    """调用系统启用写入审计记录。"""
    system = MagicMock()
    system.system_id = "sys_1"
    system.status = CallerSystemStatus.DRAFT
    system.owner = "owner"
    system.contact = "contact"
    system.effective_to = None
    policy = CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns='["/api/runtime/v1/tools/execute"]',
        qps_limit=10,
        concurrency_limit=5,
        quota_per_day=1000,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(side_effect=[system, system, system, policy])
    db.execute = AsyncMock(
        side_effect=[
            _execute_result([MagicMock()]),
            _execute_result([MagicMock()]),
        ],
    )
    svc = CallerSystemService(db)

    await svc.enable("sys_1")

    records = _audit_records(db)
    assert any(r.action == "caller_system.enable" for r in records)


async def test_caller_system_update_records_audit() -> None:
    """调用系统主记录修改写入审计记录（含变更前后摘要）。"""
    system = MagicMock()
    system.system_id = "sys_1"
    system.name = "old-name"
    system.description = "old-desc"
    system.department = "old-dept"
    system.owner = "old-owner"
    system.contact = "old-contact"
    system.effective_from = None
    system.effective_to = None
    system.row_version = 0
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=system)
    svc = CallerSystemService(db)
    set_audit_actor("acc-9", "operator")

    await svc.update_system("sys_1", name="new-name", owner="new-owner")

    records = _audit_records(db)
    assert len(records) == 1
    assert records[0].action == "caller_system.update"
    assert records[0].result == "success"
    assert '"name": "old-name"' in records[0].before_summary
    assert '"name": "new-name"' in records[0].after_summary


async def test_offboard_account_records_offboarded_status() -> None:
    """离职审计摘要记录 offboarded 状态。"""
    account = _account()
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar = AsyncMock(return_value=account)
    svc = AccountService(db, AdminSecuritySettings())
    set_audit_actor("acc-9", "operator")

    with patch(
        "toolhive.services.account_service.revoke_all_sessions",
        AsyncMock(),
    ), patch(
        "toolhive.services.account_service.RoleService",
    ) as role_cls:
        role_svc = role_cls.return_value
        role_svc.is_super_admin_account = AsyncMock(return_value=False)
        await svc.offboard_account(account, operator_id="acc-9")

    records = _audit_records(db)
    offboard = next(r for r in records if r.action == "account.offboard")
    assert '"status": "offboarded"' in offboard.after_summary
