"""MCP Server 入口：官方 SDK v2 低层 Server 动态工具暴露（阶段 3）。"""

from __future__ import annotations

import logging

from mcp import types as mcp_types
from mcp.server.lowlevel.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from toolhive.infrastructure import database
from toolhive.mcp.auth import current_mcp_identity
from toolhive.runtime.mcp_tools.executor import McpCallExecutor
from toolhive.runtime.mcp_tools.service import McpCatalogService

logger = logging.getLogger(__name__)

# MCP 端点对外挂载前缀（宿主 FastAPI mount 前缀）
MCP_MOUNT_PATH = "/mcp"


async def _handle_list_tools(
    _ctx: ServerRequestContext,
    _params: mcp_types.PaginatedRequestParams | None,
) -> mcp_types.ListToolsResult:
    """按当前 MCP 客户端授权动态返回可发现工具列表。"""
    identity = current_mcp_identity.get()
    if identity is None:
        return mcp_types.ListToolsResult(tools=[])
    async with database.async_session_factory() as session:
        listings = await McpCatalogService(
            session, identity.client.id,
        ).list_authorized()
    tools = [
        mcp_types.Tool(
            name=item.full_code,
            title=item.name,
            description=item.description,
            inputSchema=item.input_schema,
        )
        for item in listings
    ]
    return mcp_types.ListToolsResult(tools=tools)


async def _handle_call_tool(
    _ctx: ServerRequestContext,
    params: mcp_types.CallToolRequestParams,
) -> mcp_types.CallToolResult:
    """执行 MCP 工具调用：复用现有 execute 决策链并映射结果。"""
    identity = current_mcp_identity.get()
    if identity is None:
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="认证失败")],
            isError=True,
        )
    async with database.async_session_factory() as session:
        outcome = await McpCallExecutor(
            session,
            client_id=identity.client.id,
            source_ip=identity.source_ip,
        ).execute(params.name, params.arguments or {})
    return mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=outcome.text)],
        structuredContent=outcome.structured,
        isError=outcome.is_error,
    )


_server = Server(
    "ToolHive",
    version="0.1.0",
    description="ToolHive MCP 入口",
    on_list_tools=_handle_list_tools,
    on_call_tool=_handle_call_tool,
)


def get_server() -> Server:
    """返回 MCP Server 单例，供宿主 lifespan 进入 session_manager。"""
    return _server


_mcp_app: Starlette | None = None
_transport_security: TransportSecuritySettings | None = None

# 内置回环默认值：init.sql 未初始化或后台未配置时的兜底白名单
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]


def _normalize_allowed_hosts(hosts: list[str]) -> list[str]:
    """把后台配置的 Host 白名单补齐为 SDK 可匹配的形式。

    SDK 的 ``TransportSecurityMiddleware`` 只做"精确匹配"或"``:*`` 通配匹配"，
    因此对不带端口的条目要同时补一条 ``host:*``，否则 ``Host: 127.0.0.1:8100``
    这类请求会被判为非法（返回 421）。
    """
    normalized: list[str] = []
    for raw in hosts:
        host = str(raw).strip()
        if not host or host in normalized:
            continue
        normalized.append(host)
        if host.endswith(":*"):
            continue
        if host.startswith("["):
            has_port = "]:" in host
        else:
            has_port = ":" in host
        if not has_port:
            wildcard = f"{host}:*"
            if wildcard not in normalized:
                normalized.append(wildcard)
    return normalized


def get_transport_security() -> TransportSecuritySettings:
    """返回进程内共享的传输安全设置（MCP 每次请求都会重新读取）。"""
    global _transport_security
    if _transport_security is None:
        _transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_normalize_allowed_hosts(DEFAULT_ALLOWED_HOSTS),
        )
    return _transport_security


def apply_allowed_hosts(hosts: list[str]) -> None:
    """用后台 ``mcp_server_config.allowed_hosts`` 覆盖 Host 白名单。

    在应用启动阶段调用；空配置或全部非法时退回内置回环默认值，避免把 MCP
    入口锁死。SDK 侧每次请求读取同一个 settings 对象，因此无需重建应用。
    """
    normalized = _normalize_allowed_hosts(hosts) if hosts else []
    get_transport_security().allowed_hosts = (
        normalized or _normalize_allowed_hosts(DEFAULT_ALLOWED_HOSTS)
    )


def get_mcp_app() -> Starlette:
    """返回可挂载的 MCP Starlette 子应用（惰性构建，进程内复用）。"""
    global _mcp_app
    if _mcp_app is None:
        # streamable_http_path="/"：以宿主挂载前缀（/mcp）作为完整公开路径
        _mcp_app = _server.streamable_http_app(
            streamable_http_path="/",
            transport_security=get_transport_security(),
        )
    return _mcp_app
