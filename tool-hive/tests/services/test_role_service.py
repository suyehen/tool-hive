"""后台角色服务测试：内置超管角色保护（不使用角色名推导超管标志）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.enums import OperationStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import SUPER_ADMIN_ROLE_NAME
from toolhive.models.management_operation import ManagementOperation
from toolhive.models.management_role import ManagementRole
from toolhive.models.management_role_operation import ManagementRoleOperation
from toolhive.services.role_service import RoleService, build_role_filters


def test_role_domain_tablenames_share_prefix() -> None:
    """角色域表名与类名统一 management_role 前缀。"""
    assert ManagementRole.__tablename__ == "management_role"
    assert ManagementRoleOperation.__tablename__ == "management_role_operation"


def test_build_role_filters_keyword_matches_code_and_name() -> None:
    """关键词过滤同时命中角色编码与角色名。"""
    conditions = build_role_filters(keyword="ops")
    assert len(conditions) == 1
    text = str(conditions[0]).lower()
    assert "code" in text
    assert "name" in text
    assert "like" in text


def test_build_role_filters_status_and_empty() -> None:
    """状态精确过滤；空条件（含纯空白）不产生过滤条件。"""
    conditions = build_role_filters(status="active")
    assert len(conditions) == 1
    assert build_role_filters() == []
    assert build_role_filters(keyword="   ") == []


async def test_list_roles_applies_filters() -> None:
    """角色列表查询把过滤条件带到 count 与列表语句。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [MagicMock()]
    db.execute = AsyncMock(return_value=result)
    svc = RoleService(db)

    items, total = await svc.list_roles(keyword="ops", status="active")

    assert total == 1
    assert len(items) == 1
    select_stmt = db.execute.call_args.args[0]
    assert select_stmt.whereclause is not None


async def test_get_role_accounts_returns_assigned_accounts() -> None:
    """查询角色下的账号列表（先校验角色存在）。"""
    account = MagicMock()
    db = AsyncMock()
    db.get = AsyncMock(return_value=ManagementRole(name="ops"))
    result = MagicMock()
    result.scalars.return_value.all.return_value = [account]
    db.execute = AsyncMock(return_value=result)
    svc = RoleService(db)

    accounts = await svc.get_role_accounts("role-1")

    assert accounts == [account]
    db.get.assert_awaited_once_with(ManagementRole, "role-1")


async def test_get_role_accounts_raises_not_found() -> None:
    """角色不存在时抛出 NotFoundError。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    svc = RoleService(db)

    with pytest.raises(NotFoundError):
        await svc.get_role_accounts("missing")


async def test_sync_operation_codes_inserts_meta_fields() -> None:
    """启动同步：新增操作码写入代码映射的中文名/分类/排序/说明。"""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)
    svc._get_super_admin_role_ids = AsyncMock(return_value=[])

    await svc.sync_operation_codes()

    added_ops = [
        call.args[0] for call in db.add.call_args_list
        if isinstance(call.args[0], ManagementOperation)
    ]
    assert added_ops
    admin_view = next(
        op for op in added_ops if op.operation_code == "admin_account:view"
    )
    assert admin_view.display_name == "查看管理账号"
    assert admin_view.category == "account"
    assert admin_view.sort_order == 10
    assert admin_view.description is not None


async def test_sync_operation_codes_overwrites_meta_fields() -> None:
    """启动同步：已有操作码的显示名/分类/排序/说明强制刷新为代码映射。"""
    op = ManagementOperation(
        operation_code="role:view",
        display_name="role:view",
        category="old",
        sort_order=0,
        description=None,
        status=OperationStatus.ACTIVE,
    )
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [op]
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)
    svc._get_super_admin_role_ids = AsyncMock(return_value=[])

    await svc.sync_operation_codes()

    assert op.display_name == "查看后台角色"
    assert op.category == "role"
    assert op.sort_order == 10
    assert op.description is not None


async def test_sync_operation_codes_queries_super_admin_roles_once() -> None:
    """回归：超管角色 ID 只查询一次（不在枚举循环内重复查询）。"""
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)
    get_ids = AsyncMock(return_value=[])
    svc._get_super_admin_role_ids = get_ids

    await svc.sync_operation_codes()

    get_ids.assert_awaited_once()


async def test_create_role_rejects_reserved_super_admin_name() -> None:
    """禁止创建名为 super_admin 的角色。"""
    db = AsyncMock()
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.create_role("ops", SUPER_ADMIN_ROLE_NAME)
    assert "不可创建" in str(exc_info.value)


async def test_create_role_rejects_reserved_super_admin_code() -> None:
    """禁止创建编码为 super_admin 的角色。"""
    db = AsyncMock()
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.create_role("super_admin", "超级管理员")
    assert "不可使用" in str(exc_info.value)


async def test_create_role_normal_role_not_super_admin() -> None:
    """普通角色 is_super_admin 固定为 False，不依赖角色名。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)

    role = await svc.create_role("ops", "ops")
    assert role.is_super_admin is False
    assert role.code == "ops"
    assert role.sort_order == 0
    assert role.is_builtin is False


async def test_create_role_with_sort_order() -> None:
    """创建角色支持指定排序值。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)

    role = await svc.create_role("ops", "运维", sort_order=10)

    assert role.sort_order == 10


async def test_create_role_rejects_duplicate_code() -> None:
    """角色编码重复时拒绝创建。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[MagicMock(), None])
    svc = RoleService(db)

    with pytest.raises(ConflictError) as exc_info:
        await svc.create_role("ops", "运维")
    assert "已被使用" in str(exc_info.value)


async def test_update_role_rejects_renaming_to_reserved_name() -> None:
    """禁止把普通角色改名为 super_admin。"""
    role = ManagementRole(name="ops")
    role.row_version = 0
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.update_role("role-1", name=SUPER_ADMIN_ROLE_NAME)
    assert "不可使用" in str(exc_info.value)


async def test_update_role_updates_sort_order() -> None:
    """修改角色支持更新排序值。"""
    role = ManagementRole(name="ops")
    role.sort_order = 0
    role.row_version = 0
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)

    updated = await svc.update_role("role-1", sort_order=5)

    assert updated.sort_order == 5


async def test_ensure_super_admin_role_backfills_code_and_builtin() -> None:
    """存量库中的超管角色补齐编码与内置标志。"""
    role = ManagementRole(name="super_admin")
    role.code = None
    role.is_builtin = False
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=role)
    db.add = MagicMock()
    svc = RoleService(db)

    result = await svc.ensure_super_admin_role()

    assert result.code == "super_admin"
    assert result.is_builtin is True


async def test_remove_operations_rejects_super_admin_without_deleting() -> None:
    """超管角色移除操作项被拒绝，且不会执行任何删除。"""
    role = ManagementRole(name="super_admin", is_super_admin=True)
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.remove_operations("role-1", ["account:view"])
    assert "不能移除" in str(exc_info.value)
    db.delete.assert_not_called()
