"""调用系统运行策略、工具范围与紧急禁用测试（H06）。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.enums import CallerSystemStatus
from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.management_audit_log import ManagementAuditLog
from toolhive.services.audit_service import set_audit_actor
from toolhive.services.caller_system_service import CallerSystemService


@pytest.fixture(autouse=True)
def _reset_actor() -> None:
    """每个测试前后清空当前操作人。"""
    set_audit_actor(None, None)
    yield
    set_audit_actor(None, None)


def _system(status: str = CallerSystemStatus.DRAFT) -> MagicMock:
    system = MagicMock()
    system.system_id = "sys_1"
    system.status = status
    system.owner = "owner"
    system.contact = "contact"
    system.effective_to = None
    return system


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


async def test_save_runtime_policy_creates_when_missing() -> None:
    """策略不存在时创建，并写入 JSON 格式的 API 范围。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), None])
    db.add = MagicMock()
    svc = CallerSystemService(db)
    set_audit_actor("acc-9", "operator")

    policy = await svc.save_runtime_policy(
        system_id="sys_1",
        allowed_api_patterns=["/api/runtime/v1/tools/execute"],
        qps_limit=10,
        concurrency_limit=5,
        quota_per_day=1000,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )

    assert isinstance(policy, CallerRuntimePolicy)
    assert policy.system_id == "sys_1"
    assert policy.qps_limit == 10
    assert policy.get_allowed_api_patterns() == ["/api/runtime/v1/tools/execute"]
    # 创建时写入创建时间与当前操作人 ID
    assert policy.create_time is not None
    assert policy.create_by == "acc-9"
    audits = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementAuditLog)
    ]
    assert len(audits) == 1
    assert audits[0].action == "caller_policy.save"


async def test_save_runtime_policy_updates_existing() -> None:
    """策略已存在时更新并递增乐观锁版本。"""
    existing = CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns=json.dumps(["/api/runtime/v1/tools/execute"]),
        qps_limit=1,
        concurrency_limit=1,
        quota_per_day=1,
        request_timeout_seconds=10,
        circuit_breaker_enabled=False,
    )
    existing.row_version = 2
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), existing])
    db.add = MagicMock()
    svc = CallerSystemService(db)
    set_audit_actor("acc-9", "operator")

    policy = await svc.save_runtime_policy(
        system_id="sys_1",
        allowed_api_patterns=["/api/runtime/v1/tools/execute"],
        qps_limit=20,
        concurrency_limit=8,
        quota_per_day=2000,
        request_timeout_seconds=60,
        circuit_breaker_enabled=True,
        expected_row_version=2,
    )

    assert policy.row_version == 3
    assert policy.qps_limit == 20
    # 更新时写入修改时间与当前操作人 ID
    assert policy.update_time is not None
    assert policy.update_by == "acc-9"
    audits = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementAuditLog)
    ]
    assert len(audits) == 1
    assert audits[0].action == "caller_policy.save"


async def test_save_runtime_policy_rejects_empty_patterns() -> None:
    """运行 API 范围为空时拒绝保存。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_system())
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError):
        await svc.save_runtime_policy(
            system_id="sys_1",
            allowed_api_patterns=[],
            qps_limit=10,
            concurrency_limit=5,
            quota_per_day=1000,
            request_timeout_seconds=30,
            circuit_breaker_enabled=True,
        )


async def test_get_runtime_policy_missing_returns_none() -> None:
    """未配置策略时返回 None（不抛错）。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), None])
    svc = CallerSystemService(db)
    assert await svc.get_runtime_policy("sys_1") is None


async def test_replace_tool_scopes() -> None:
    """全量替换工具范围：删除旧记录、写入新集合。"""
    old_scope = MagicMock()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[_system(), _system()])
    db.execute = AsyncMock(return_value=_execute_result([old_scope]))
    db.delete = AsyncMock()
    db.add = MagicMock()
    svc = CallerSystemService(db)
    set_audit_actor("acc-9", "operator")

    scopes = await svc.replace_tool_scopes(
        "sys_1",
        [
            {"scope_type": "tool", "scope_code": "tool.a", "status": "active"},
            {"scope_type": "capability", "scope_code": "cap.x", "status": "disabled"},
        ],
    )

    assert len(scopes) == 2
    assert all(isinstance(s, CallerToolScope) for s in scopes)
    # 全量替换时新记录写入创建时间与当前操作人 ID
    assert all(s.create_time is not None for s in scopes)
    assert all(s.create_by == "acc-9" for s in scopes)
    db.delete.assert_called_once_with(old_scope)
    assert db.add.call_count == 3  # 2 条范围 + 1 条审计


async def test_replace_tool_scopes_rejects_invalid_type_before_delete() -> None:
    """非法范围类型在删除旧记录之前就被拒绝。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_system())
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError):
        await svc.replace_tool_scopes(
            "sys_1",
            [{"scope_type": "bogus", "scope_code": "x", "status": "active"}],
        )
    db.delete.assert_not_called()


async def test_emergency_disable_and_enable() -> None:
    """系统级紧急禁用/解除字段流转。"""
    system = _system(status=CallerSystemStatus.ENABLED)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=system)
    db.add = MagicMock()
    svc = CallerSystemService(db)
    set_audit_actor("acc-9", "operator")

    disabled = await svc.emergency_disable("sys_1", "安全事件")
    assert disabled.emergency_disabled is True
    assert disabled.emergency_disabled_reason == "安全事件"
    # 状态变更写入修改时间与当前操作人 ID
    assert disabled.update_time is not None
    assert disabled.update_by == "acc-9"

    enabled = await svc.emergency_enable("sys_1")
    assert enabled.emergency_disabled is False
    assert enabled.emergency_disabled_reason is None
    assert enabled.update_time is not None
    assert enabled.update_by == "acc-9"


async def test_emergency_disable_rejects_non_enabled() -> None:
    """只有已启用的调用系统可以紧急禁用。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_system(status=CallerSystemStatus.DRAFT))
    svc = CallerSystemService(db)

    with pytest.raises(ConflictError):
        await svc.emergency_disable("sys_1", "测试")


async def test_enable_rejects_without_runtime_policy() -> None:
    """启用校验增强：缺少运行策略（API 范围）时拒绝启用。"""
    system = _system()
    key = MagicMock()
    rule = MagicMock()
    db = AsyncMock()
    # get_by_system_id ×3（enable、_check、get_runtime_policy）+ policy 查询 None
    db.scalar = AsyncMock(side_effect=[system, system, system, None])
    db.execute = AsyncMock(
        side_effect=[_execute_result([key]), _execute_result([rule])],
    )
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.enable("sys_1")
    assert "缺少运行策略" in str(exc_info.value)


async def test_enable_succeeds_with_runtime_policy() -> None:
    """运行策略已配置且其他条件满足时允许启用。"""
    system = _system()
    key = MagicMock()
    rule = MagicMock()
    policy = CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns=json.dumps(["/api/runtime/v1/tools/execute"]),
        qps_limit=10,
        concurrency_limit=5,
        quota_per_day=1000,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[system, system, system, policy])
    db.execute = AsyncMock(
        side_effect=[_execute_result([key]), _execute_result([rule])],
    )
    db.add = MagicMock()
    svc = CallerSystemService(db)

    result = await svc.enable("sys_1")
    assert result.status == CallerSystemStatus.ENABLED


async def test_revive_rejects_without_runtime_policy() -> None:
    """恢复启用同样校验前置条件：缺少运行策略时拒绝。"""
    system = _system(status=CallerSystemStatus.DISABLED)
    key = MagicMock()
    rule = MagicMock()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[system, system, system, None])
    db.execute = AsyncMock(
        side_effect=[_execute_result([key]), _execute_result([rule])],
    )
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.revive("sys_1")
    assert "缺少运行策略" in str(exc_info.value)


async def test_revive_succeeds_with_conditions() -> None:
    """前置条件满足时允许恢复启用。"""
    system = _system(status=CallerSystemStatus.DISABLED)
    key = MagicMock()
    rule = MagicMock()
    policy = CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns=json.dumps(["/api/runtime/v1/tools/execute"]),
        qps_limit=10,
        concurrency_limit=5,
        quota_per_day=1000,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[system, system, system, policy])
    db.execute = AsyncMock(
        side_effect=[_execute_result([key]), _execute_result([rule])],
    )
    db.add = MagicMock()
    svc = CallerSystemService(db)

    result = await svc.revive("sys_1")
    assert result.status == CallerSystemStatus.ENABLED


async def test_revive_keeps_emergency_disabled_flag() -> None:
    """恢复启用不清除紧急禁用标志（独立覆盖，需显式解除）。"""
    system = _system(status=CallerSystemStatus.DISABLED)
    system.emergency_disabled = True
    system.emergency_disabled_reason = "安全事件"
    key = MagicMock()
    rule = MagicMock()
    policy = CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns=json.dumps(["/api/runtime/v1/tools/execute"]),
        qps_limit=10,
        concurrency_limit=5,
        quota_per_day=1000,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[system, system, system, policy])
    db.execute = AsyncMock(
        side_effect=[_execute_result([key]), _execute_result([rule])],
    )
    db.add = MagicMock()
    svc = CallerSystemService(db)

    result = await svc.revive("sys_1")
    assert result.status == CallerSystemStatus.ENABLED
    assert result.emergency_disabled is True
    assert result.emergency_disabled_reason == "安全事件"
