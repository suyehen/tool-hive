"""调用系统基础信息服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.enums import PublicKeyStatus
from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.models.caller_system import CallerSystem
from toolhive.services.caller_system_service import (
    CallerSystemService,
    build_caller_system_filters,
)


def _generate_rsa_public_key_pem(key_size: int = 2048) -> str:
    """生成 RSA 公钥 PEM（测试辅助）。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    return key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def test_tags_roundtrip() -> None:
    """标签 JSON 数组序列化与解析往返一致。"""
    system = CallerSystem(system_id="sys_1", name="test", environment="development")
    system.set_tags(["erp", "订单"])
    assert system.tags == '["erp", "订单"]'
    assert system.get_tags() == ["erp", "订单"]
    system.set_tags([])
    assert system.get_tags() == []


def test_build_caller_system_filters_keyword_matches_identity_fields() -> None:
    """关键词过滤同时命中编码/名称/system_id。"""
    conditions = build_caller_system_filters(keyword="erp")
    assert len(conditions) == 1
    text = str(conditions[0]).lower()
    assert "code" in text
    assert "name" in text
    assert "system_id" in text
    assert "like" in text


def test_build_caller_system_filters_status_environment_and_empty() -> None:
    """状态/环境精确过滤；空条件（含纯空白）不产生过滤条件。"""
    conditions = build_caller_system_filters(
        status="enabled", environment="production",
    )
    assert len(conditions) == 2
    assert build_caller_system_filters() == []
    assert build_caller_system_filters(keyword="   ") == []


async def test_list_systems_applies_filters() -> None:
    """调用系统列表查询把过滤条件带到 count 与列表语句。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)
    result = MagicMock()
    result.scalars.return_value.all.return_value = [MagicMock()]
    db.execute = AsyncMock(return_value=result)
    svc = CallerSystemService(db)

    items, total = await svc.list_systems(
        keyword="erp", status="enabled", environment="production",
    )

    assert total == 1
    assert len(items) == 1
    select_stmt = db.execute.call_args.args[0]
    assert select_stmt.whereclause is not None


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


async def test_add_public_key_rejects_unknown_algorithm() -> None:
    """未注册的签名算法在入库前被拒绝。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError, match="不支持的签名算法"):
        await svc.add_public_key(
            "sys_1", public_key="not-a-pem", algorithm="SM2-SM3",
        )


async def test_add_public_key_rejects_malformed_public_key() -> None:
    """畸形公钥在入库前被拒绝。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError, match="公钥格式无效"):
        await svc.add_public_key(
            "sys_1", public_key="not-a-pem", algorithm="RSA-PSS-SHA256",
        )


async def test_add_public_key_rejects_weak_rsa_key() -> None:
    """低于默认阈值的 RSA 公钥被拒绝。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CallerSystemService(db)

    with pytest.raises(ValidationError, match="位长不足"):
        await svc.add_public_key(
            "sys_1",
            public_key=_generate_rsa_public_key_pem(key_size=1024),
            algorithm="RSA-PSS-SHA256",
        )


async def test_add_public_key_honors_configured_min_bits() -> None:
    """运行侧配置的 RSA 最小位长实时生效。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=MagicMock())
    svc = CallerSystemService(
        db, runtime_security=RuntimeSecuritySettings(signing_key_min_bits=3072),
    )

    with pytest.raises(ValidationError, match="位长不足"):
        await svc.add_public_key(
            "sys_1",
            public_key=_generate_rsa_public_key_pem(key_size=2048),
            algorithm="RSA-PSS-SHA256",
        )


async def test_add_public_key_accepts_valid_rsa_key() -> None:
    """合法 RSA 公钥成功登记为待启用状态。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[MagicMock(), None])
    db.add = MagicMock()
    svc = CallerSystemService(db)

    with patch.object(svc, "generate_key_id", return_value="key_test"):
        key = await svc.add_public_key(
            "sys_1",
            public_key=_generate_rsa_public_key_pem(),
            algorithm="RSA-PSS-SHA256",
        )

    assert key.algorithm == "RSA-PSS-SHA256"
    assert key.status == PublicKeyStatus.PENDING
    assert key.fingerprint
