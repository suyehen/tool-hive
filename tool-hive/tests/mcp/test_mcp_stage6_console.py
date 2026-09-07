"""MCP 阶段 6 测试：协议级调试台内置客户端与会话执行。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from toolhive.core.enums import McpClientStatus
from toolhive.core.exceptions import NotFoundError
from toolhive.mcp.console import (
    CONSOLE_CLIENT_CODE,
    _prepare_console_client,
    run_console_session,
)
from toolhive.models.mcp_client import McpClient
from toolhive.models.mcp_client_token import McpClientToken


class _SessionContext:
    """模拟 async with 数据库会话。"""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return False


def _factory(session):
    return lambda: _SessionContext(session)


def _client() -> McpClient:
    return McpClient(
        id="client_console",
        client_code=CONSOLE_CLIENT_CODE,
        name="内置调试客户端",
        status=McpClientStatus.DISABLED,
    )


async def test_prepare_console_client_creates_and_enables() -> None:
    """缺少内置客户端时自动创建、配置规则并签发 Token。"""
    session = AsyncMock()
    service = AsyncMock()
    service.get_by_client_code = AsyncMock(side_effect=NotFoundError("不存在"))
    service.create_client = AsyncMock(return_value=_client())
    service.list_ip_rules = AsyncMock(return_value=[])
    service.add_ip_rule = AsyncMock()
    service.issue_token = AsyncMock(
        return_value=(McpClientToken(id="token_1", token_hash="h", token_key="k"), "plain-token")
    )
    service.enable = AsyncMock()
    with patch("toolhive.mcp.console.McpClientService", return_value=service):
        code, token = await _prepare_console_client(session)
    assert code == CONSOLE_CLIENT_CODE
    assert token == "plain-token"
    service.create_client.assert_awaited_once()
    service.add_ip_rule.assert_awaited_once()
    service.enable.assert_awaited_once()


async def test_run_console_session_returns_summary() -> None:
    """调试会话返回协议摘要并吊销一次性 Token。"""
    session = AsyncMock()
    factory = _factory(session)
    service = AsyncMock()
    service.get_by_client_code = AsyncMock(
        return_value=_client(),
    )
    service.revive = AsyncMock()
    service.list_ip_rules = AsyncMock(
        return_value=[MagicMock(ip_cidr="127.0.0.1")],
    )
    service.issue_token = AsyncMock(
        return_value=(McpClientToken(id="token_1", token_hash="h", token_key="k"), "plain-token")
    )
    service.enable = AsyncMock()
    service.revoke_token = AsyncMock()
    with patch("toolhive.mcp.console.database.async_session_factory", factory):
        with patch("toolhive.mcp.console.McpClientService", return_value=service):
            with patch(
                "toolhive.mcp.console._perform_mcp_session",
                AsyncMock(
                    return_value={
                        "server_name": "ToolHive",
                        "discovered": ["math.basic.calculator"],
                        "call_text": "ok",
                        "call_is_error": False,
                    }
                ),
            ), patch(
                "toolhive.mcp.console._latest_trace_id",
                AsyncMock(return_value="trace_console"),
            ):
                result = await run_console_session(
                    "math.basic.calculator", {"a": 1},
                )
    assert result.ok
    assert result.server_name == "ToolHive"
    assert result.trace_id == "trace_console"
    service.revoke_token.assert_awaited_once()
