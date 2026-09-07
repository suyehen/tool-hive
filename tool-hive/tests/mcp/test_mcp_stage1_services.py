"""MCP 阶段 1（数据模型与基础服务）测试。"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.core.enums import (
    McpClientStatus,
    McpTokenStatus,
    ToolScopeStatus,
)
from toolhive.core.exceptions import ValidationError
from toolhive.core.operation_codes import OPERATION_META, OperationCode
from toolhive.models.mcp_client import McpClient
from toolhive.models.mcp_client_scope import McpClientScope
from toolhive.services.catalog_scope_validator import CatalogScopeValidator
from toolhive.services.mcp_client_service import McpClientService


def test_mcp_operation_codes_registered() -> None:
    """MCP 域操作码必须全部登记到操作码元数据。"""
    mcp_codes = {
        OperationCode.MCP_SERVER_VIEW,
        OperationCode.MCP_SERVER_CONFIG,
        OperationCode.MCP_CLIENT_VIEW,
        OperationCode.MCP_CLIENT_MANAGE,
        OperationCode.MCP_CLIENT_ALLOW_ANY_IP,
        OperationCode.MCP_AUTH_VIEW,
        OperationCode.MCP_AUTH_MANAGE,
    }
    for code in mcp_codes:
        assert str(code) in OPERATION_META


async def test_enable_conditions_require_token_and_ip_rule() -> None:
    """启用前置条件要求 ACTIVE 令牌与 ACTIVE 来源 IP 规则。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[0, 0])
    svc = McpClientService(db)
    conditions = await svc._check_enable_conditions("client_1")
    assert any("令牌" in condition for condition in conditions)
    assert any("IP 规则" in condition for condition in conditions)


async def test_enable_conditions_pass_with_valid_credentials() -> None:
    """令牌与来源规则齐备时启用前置条件为空。"""
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[1, 1])
    svc = McpClientService(db)
    conditions = await svc._check_enable_conditions("client_1")
    assert conditions == []


async def test_issue_token_returns_plaintext_once_and_hashes_stored() -> None:
    """签发令牌：明文返回一次，库中只保存哈希。"""
    db = AsyncMock()
    db.add = MagicMock()
    client = McpClient(
        id="client_1",
        client_code="mcp_test",
        name="测试客户端",
        status=McpClientStatus.DRAFT,
    )
    svc = McpClientService(db)
    svc.get_by_client_code = AsyncMock(return_value=client)
    svc._revoke_active_tokens = AsyncMock()

    record, token = await svc.issue_token("mcp_test")
    assert token
    assert record.status == McpTokenStatus.ACTIVE
    assert record.token_hash != token
    assert record.token_key == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert db.add.called


async def test_replace_scopes_trim_scope_code() -> None:
    """保存授权范围时统一 trim 编码，保证运行侧精确匹配一致。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    client = McpClient(
        id="client_1",
        client_code="mcp_test",
        name="测试客户端",
        status=McpClientStatus.DRAFT,
    )
    svc = McpClientService(db)
    svc.get_by_client_code = AsyncMock(return_value=client)
    svc.list_scopes = AsyncMock(return_value=[])
    with patch(
        "toolhive.services.mcp_client_service.CatalogScopeValidator"
    ) as validator_cls:
        validator_cls.return_value.validate_items = AsyncMock()
        result = await svc.replace_scopes(
            "mcp_test",
            [{
                "scope_type": "tool",
                "scope_code": " math.basic.calculator ",
                "status": ToolScopeStatus.ACTIVE,
            }],
        )
    assert isinstance(result[0], McpClientScope)
    assert result[0].scope_code == "math.basic.calculator"


async def test_scope_validator_rejects_unknown_namespace() -> None:
    """命名空间范围必须引用真实存在的非归档工具命名空间。"""
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    validator = CatalogScopeValidator(db)
    with pytest.raises(ValidationError):
        await validator.validate_items(
            [{
                "scope_type": "namespace",
                "scope_code": "missing.ns",
                "status": "active",
            }]
        )


async def test_scope_validator_reference_map_reports_missing() -> None:
    """引用状态映射对不存在的编码返回 (False, False)。"""
    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[]))
            )
        )
    )
    scope = McpClientScope(
        client_id="client_1",
        scope_type="tool",
        scope_code="missing.tool",
        status=ToolScopeStatus.ACTIVE,
    )
    validator = CatalogScopeValidator(db)
    refs = await validator.reference_map([scope])
    assert refs[("tool", "missing.tool")] == (False, False)
