"""MCP 阶段 2 认证链路测试：认证服务与宿主鉴权中间件。"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from toolhive.core.enums import IPRuleStatus, McpClientStatus
from toolhive.mcp.auth import (
    MCP_AUTH_CLIENT_DISABLED,
    MCP_AUTH_SOURCE_NOT_ALLOWED,
    MCP_AUTH_TOKEN_INVALID,
    MCP_SERVER_DISABLED,
    McpAuthError,
    McpAuthService,
)
from toolhive.mcp.middleware import McpAuthMiddleware
from toolhive.models.mcp_client import McpClient
from toolhive.models.mcp_client_ip_rule import McpClientIpRule
from toolhive.models.mcp_client_token import McpClientToken
from toolhive.models.mcp_server_config import McpServerConfig
from toolhive.services.security.password import hash_password

_TOKEN = "stage2-valid-token"
_TOKEN_KEY = hashlib.sha256(_TOKEN.encode("utf-8")).hexdigest()


def _config(enabled: bool = True) -> McpServerConfig:
    return McpServerConfig(
        id="default", server_name="ToolHive", enabled=enabled,
        allowed_hosts=["127.0.0.1"],
    )


def _client(status: str = McpClientStatus.ENABLED) -> McpClient:
    return McpClient(
        id="client_1",
        client_code="mcp_auth_test",
        name="认证测试客户端",
        status=status,
    )


def _token_record() -> McpClientToken:
    return McpClientToken(
        id="token_1",
        client_id="client_1",
        token_hash=hash_password(_TOKEN),
        token_key=_TOKEN_KEY,
        status="active",
    )


def _rule() -> McpClientIpRule:
    return McpClientIpRule(
        id="rule_1", client_id="client_1", ip_cidr="127.0.0.1",
        status=IPRuleStatus.ACTIVE,
    )


def _service(db, source_ip: str = "127.0.0.1") -> McpAuthService:
    return McpAuthService(db, source_ip)


async def test_auth_accepts_valid_token() -> None:
    """有效 Token + 启用客户端 + 命中来源规则时认证通过。"""
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[_config(), _client()])
    db.scalar = AsyncMock(return_value=_token_record())
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[_rule()]))
            )
        )
    )
    identity = await _service(db).authenticate(_TOKEN)
    assert identity.client.client_code == "mcp_auth_test"


async def test_auth_rejects_disabled_client() -> None:
    """客户端非 enabled 时统一返回 401。"""
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[_config(), _client(McpClientStatus.DISABLED)])
    db.scalar = AsyncMock(return_value=_token_record())
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[_rule()]))
            )
        )
    )
    with pytest.raises(McpAuthError) as exc_info:
        await _service(db).authenticate(_TOKEN)
    assert exc_info.value.code == MCP_AUTH_CLIENT_DISABLED


async def test_auth_rejects_wrong_token() -> None:
    """Token 与哈希不匹配时拒绝。"""
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[_config(), _client()])
    wrong = _token_record()
    wrong.token_hash = hash_password("another-token")
    db.scalar = AsyncMock(return_value=wrong)
    with pytest.raises(McpAuthError) as exc_info:
        await _service(db).authenticate(_TOKEN)
    assert exc_info.value.code == MCP_AUTH_TOKEN_INVALID


async def test_auth_rejects_source_not_allowed() -> None:
    """来源 IP 未命中规则时拒绝。"""
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[_config(), _client()])
    db.scalar = AsyncMock(return_value=_token_record())
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[_rule()]))
            )
        )
    )
    with pytest.raises(McpAuthError) as exc_info:
        await _service(db, source_ip="10.0.0.9").authenticate(_TOKEN)
    assert exc_info.value.code == MCP_AUTH_SOURCE_NOT_ALLOWED


async def test_auth_rejects_disabled_server() -> None:
    """MCP Server 全局停用时拒绝所有请求。"""
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[_config(enabled=False)])
    with pytest.raises(McpAuthError) as exc_info:
        await _service(db).authenticate(_TOKEN)
    assert exc_info.value.code == MCP_SERVER_DISABLED


class _AsyncSessionContext:
    """测试用异步上下文：模拟 async with 会话工厂。"""

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


def _session_factory(session):
    """构造 async with 可用的会话工厂（测试辅助）。"""
    return lambda: _AsyncSessionContext(session)


def test_middleware_rejects_without_valid_token() -> None:
    """中间件在协议处理前返回 401 且带 WWW-Authenticate。"""
    app = FastAPI()
    app.add_middleware(McpAuthMiddleware)

    @app.get("/mcp/probe")
    async def probe():
        return {"ok": True}

    session = AsyncMock()
    factory = _session_factory(session)
    with patch("toolhive.infrastructure.database.async_session_factory", factory):
        with patch(
            "toolhive.mcp.middleware.McpAuthService"
        ) as service_cls:
            service_cls.return_value.authenticate = AsyncMock(
                side_effect=McpAuthError(
                    MCP_AUTH_TOKEN_INVALID, "认证失败", 401,
                )
            )
            with patch(
                "toolhive.mcp.middleware.TraceService.log_event", AsyncMock(),
            ):
                client = TestClient(app, client=("127.0.0.1", 50000))
                resp = client.get("/mcp/probe")
    assert resp.status_code == 401
    assert "Bearer" in resp.headers.get("WWW-Authenticate", "")


def test_middleware_accepts_valid_token_and_sets_identity() -> None:
    """有效认证后请求进入路由并携带 MCP 身份。"""
    app = FastAPI()
    app.add_middleware(McpAuthMiddleware)

    @app.get("/mcp/probe")
    async def probe(request: Request):
        identity = request.state.mcp_identity
        return {"client_code": identity.client.client_code}

    session = AsyncMock()
    factory = _session_factory(session)
    identity = SimpleNamespace(
        client=SimpleNamespace(id="client_1", client_code="mcp_auth_test"),
    )
    with patch("toolhive.infrastructure.database.async_session_factory", factory):
        with patch(
            "toolhive.mcp.middleware.McpAuthService"
        ) as service_cls:
            service_cls.return_value.authenticate = AsyncMock(return_value=identity)
            with patch(
                "toolhive.mcp.middleware.TraceService.log_event", AsyncMock(),
            ):
                client = TestClient(app, client=("127.0.0.1", 50000))
                resp = client.get(
                    "/mcp/probe",
                    headers={"Authorization": f"Bearer {_TOKEN}"},
                )
    assert resp.status_code == 200
    assert resp.json()["client_code"] == "mcp_auth_test"
