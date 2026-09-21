"""归档角色终态保护测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.enums import RoleStatus
from toolhive.core.exceptions import ValidationError
from toolhive.models.account_role import AccountRole
from toolhive.models.management_role import ManagementRole
from toolhive.services.role_service import RoleService


def _archived_role() -> ManagementRole:
    role = ManagementRole(name="ops", status=RoleStatus.ARCHIVED)
    role.row_version = 0
    return role


async def test_update_role_rejects_archived() -> None:
    """归档角色不可修改基本信息。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.update_role("role-1", name="ops2")
    assert "已归档" in str(exc_info.value)


async def test_assign_operations_rejects_archived() -> None:
    """归档角色不可分配操作项。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.assign_operations("role-1", ["account:view"])
    assert "已归档" in str(exc_info.value)


async def test_remove_operations_rejects_archived() -> None:
    """归档角色不可移除操作项。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.remove_operations("role-1", ["account:view"])
    assert "已归档" in str(exc_info.value)


async def test_assign_role_to_account_rejects_archived() -> None:
    """归档角色不可授予账号。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.assign_role_to_account("acc-1", "role-1", operator_id="op-1")
    assert "已归档" in str(exc_info.value)


async def test_update_role_status_rejects_transition_from_archived() -> None:
    """归档为终态：不允许从 archived 转出。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.update_role_status("role-1", RoleStatus.ACTIVE)
    assert "已归档" in str(exc_info.value)


async def test_remove_role_from_account_allows_archived() -> None:
    """归档角色的账号关联仍可移除（清理历史关联）。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_archived_role())
    ar = MagicMock(spec=AccountRole)
    db.scalar = AsyncMock(return_value=ar)
    db.delete = AsyncMock()
    db.add = MagicMock()
    svc = RoleService(db)

    await svc.remove_role_from_account("acc-1", "role-1", operator_id="op-1")

    db.delete.assert_awaited_once_with(ar)


async def test_assign_operations_rejects_unknown_code() -> None:
    """未知操作码必须返回 400 级业务错误，而不是数据库外键异常 500。"""
    role = ManagementRole(name="ops", status=RoleStatus.ACTIVE)
    role.row_version = 0
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.assign_operations("role-1", ["definitely:not-an-operation"])
    assert "未知操作项" in str(exc_info.value)


async def test_assign_operations_deduplicates_codes() -> None:
    """重复操作码只写入一次，避免主键/唯一约束冲突。"""
    role = ManagementRole(name="ops", status=RoleStatus.ACTIVE)
    role.row_version = 0
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)

    from toolhive.core.operation_codes import OperationCode
    from toolhive.models.management_role_operation import ManagementRoleOperation

    code = next(iter(OperationCode)).value
    await svc.assign_operations("role-1", [code, code])

    assigned = [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementRoleOperation)
    ]
    assert len(assigned) == 1
    assert assigned[0].operation_code == code
