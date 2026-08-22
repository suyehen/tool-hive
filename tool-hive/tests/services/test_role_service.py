"""后台角色服务测试：内置超管角色保护（不使用角色名推导超管标志）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.exceptions import ValidationError
from toolhive.core.operation_codes import SUPER_ADMIN_ROLE_NAME
from toolhive.models.backend_role import BackendRole
from toolhive.services.role_service import RoleService


async def test_create_role_rejects_reserved_super_admin_name() -> None:
    """禁止创建名为 super_admin 的角色。"""
    db = AsyncMock()
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.create_role(SUPER_ADMIN_ROLE_NAME)
    assert "不可创建" in str(exc_info.value)


async def test_create_role_normal_role_not_super_admin() -> None:
    """普通角色 is_super_admin 固定为 False，不依赖角色名。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = RoleService(db)

    role = await svc.create_role("ops")
    assert role.is_super_admin is False


async def test_update_role_rejects_renaming_to_reserved_name() -> None:
    """禁止把普通角色改名为 super_admin。"""
    role = BackendRole(name="ops")
    role.row_version = 0
    db = AsyncMock()
    db.get = AsyncMock(return_value=role)
    svc = RoleService(db)

    with pytest.raises(ValidationError) as exc_info:
        await svc.update_role("role-1", name=SUPER_ADMIN_ROLE_NAME)
    assert "不可使用" in str(exc_info.value)
