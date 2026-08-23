"""调用系统基础信息服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.models.caller_system import CallerSystem
from toolhive.services.caller_system_service import CallerSystemService


def test_tags_roundtrip() -> None:
    """标签 JSON 数组序列化与解析往返一致。"""
    system = CallerSystem(system_id="sys_1", name="test", environment="development")
    system.set_tags(["erp", "订单"])
    assert system.tags == '["erp", "订单"]'
    assert system.get_tags() == ["erp", "订单"]
    system.set_tags([])
    assert system.get_tags() == []


async def test_create_draft_accepts_new_fields() -> None:
    """创建调用系统支持系统编码/归属方/负责人邮箱/标签与 staging 环境。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = CallerSystemService(db)

    with patch.object(svc, "generate_system_id", return_value="sys_abc"):
        system = await svc.create_draft(
            name="订单服务",
            code="erp-order",
            environment="staging",
            belonging_party="xx 事业部",
            owner_email="owner@example.com",
            tags=["erp", "订单"],
        )

    assert system.environment == "staging"
    assert system.code == "erp-order"
    assert system.belonging_party == "xx 事业部"
    assert system.owner_email == "owner@example.com"
    assert system.get_tags() == ["erp", "订单"]


async def test_create_draft_rejects_invalid_environment() -> None:
    """非法环境值被拒绝。"""
    db = AsyncMock()
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError):
        await svc.create_draft(name="x", code="x", environment="prod")


async def test_create_draft_rejects_duplicate_code_in_same_environment() -> None:
    """同一环境下系统编码重复时拒绝创建。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CallerSystemService(db)

    with pytest.raises(ConflictError) as exc_info:
        await svc.create_draft(name="订单服务", code="erp", environment="development")
    assert "已被使用" in str(exc_info.value)


async def test_create_draft_allows_same_code_in_different_environment() -> None:
    """不同环境下允许相同系统编码。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    db.add = MagicMock()
    svc = CallerSystemService(db)

    with patch.object(svc, "generate_system_id", return_value="sys_abc"):
        system = await svc.create_draft(
            name="订单服务", code="erp", environment="production",
        )

    assert system.code == "erp"
    assert system.environment == "production"


async def test_update_system_updates_new_fields() -> None:
    """更新调用系统支持归属方/负责人邮箱/标签。"""
    system = CallerSystem(system_id="sys_1", name="old", environment="development")
    system.tags = None
    system.row_version = 0
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=system)
    db.add = MagicMock()
    svc = CallerSystemService(db)

    updated = await svc.update_system(
        "sys_1",
        belonging_party="xx 事业部",
        owner_email="a@b.com",
        tags=["x"],
    )

    assert updated.belonging_party == "xx 事业部"
    assert updated.owner_email == "a@b.com"
    assert updated.get_tags() == ["x"]
