"""MCP 协议级调试台：内置测试客户端执行真实 MCP 会话。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx2
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import McpClientStatus
from toolhive.core.exceptions import NotFoundError
from toolhive.infrastructure import database
from toolhive.mcp.middleware import McpAuthMiddleware
from toolhive.mcp.server import MCP_MOUNT_PATH, get_mcp_app
from toolhive.models.mcp_client import McpClient
from toolhive.models.runtime_trace_log import RuntimeTraceLog
from toolhive.services.mcp_client_service import McpClientService

logger = logging.getLogger(__name__)

# 内置调试客户端固定标识（不对真实业务开放）
CONSOLE_CLIENT_CODE = "mcp-console-test"
CONSOLE_CLIENT_NAME = "内置调试客户端"
_CONSOLE_IP_RULE = "127.0.0.1"
_CONSOLE_URL = f"http://127.0.0.1:8000{MCP_MOUNT_PATH}/"


@dataclass
class ConsoleRunResult:
    """一次调试会话的结果摘要。"""

    ok: bool
    server_name: str
    discovered: list[str]
    call_text: str
    call_is_error: bool
    trace_id: str | None
    detail: str | None = None


async def run_console_session(
    tool_code: str, arguments: dict[str, Any],
) -> ConsoleRunResult:
    """准备内置测试客户端并发起真实 MCP 会话。"""
    async with database.async_session_factory() as session:
        client_code, token = await _prepare_console_client(session)
    host = _build_debug_host()
    try:
        summary = await _perform_mcp_session(
            host, token, tool_code, arguments,
        )
        return ConsoleRunResult(
            ok=True,
            server_name=summary.get("server_name", ""),
            discovered=summary.get("discovered", []),
            call_text=summary.get("call_text", ""),
            call_is_error=bool(summary.get("call_is_error")),
            trace_id=await _latest_trace_id(client_code),
            detail=summary.get("detail"),
        )
    except Exception as exc:
        logger.error(
            "mcp console session failed tool=%s error=%s", tool_code, exc,
        )
        return ConsoleRunResult(
            ok=False,
            server_name="",
            discovered=[],
            call_text="",
            call_is_error=True,
            trace_id=None,
            detail=f"调试会话失败: {exc}",
        )
    finally:
        async with database.async_session_factory() as session:
            try:
                await McpClientService(session).revoke_token(
                    client_code, "调试会话结束",
                )
            except NotFoundError:
                pass


def _build_debug_host() -> FastAPI:
    """构造最小调试宿主（真实认证中间件 + MCP 挂载）。"""
    host = FastAPI()
    host.add_middleware(McpAuthMiddleware)
    host.mount(MCP_MOUNT_PATH, get_mcp_app())
    return host


async def _prepare_console_client(
    session: AsyncSession,
) -> tuple[str, str]:
    """保证内置客户端可启用并签发一次性 Token，返回 (client_code, token)。"""
    service = McpClientService(session)
    try:
        client = await service.get_by_client_code(CONSOLE_CLIENT_CODE)
    except NotFoundError:
        client = await service.create_client(name=CONSOLE_CLIENT_NAME)
    if client.status == McpClientStatus.REVOKED:
        client = await service.revive(CONSOLE_CLIENT_CODE)
    rules = await service.list_ip_rules(CONSOLE_CLIENT_CODE)
    if not any(rule.ip_cidr == _CONSOLE_IP_RULE for rule in rules):
        await service.add_ip_rule(
            CONSOLE_CLIENT_CODE, ip_cidr=_CONSOLE_IP_RULE,
        )
    _record, token = await service.issue_token(CONSOLE_CLIENT_CODE)
    if client.status != McpClientStatus.ENABLED:
        await service.enable(CONSOLE_CLIENT_CODE)
    return CONSOLE_CLIENT_CODE, token


async def _perform_mcp_session(
    host: FastAPI,
    token: str,
    tool_code: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """通过官方 SDK 客户端执行 initialize / tools/list / tools/call。"""
    http_client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=host),
        headers={"Authorization": f"Bearer {token}"},
    )
    summary: dict[str, Any] = {}
    try:
        async with streamable_http_client(
            _CONSOLE_URL, http_client=http_client,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                summary["server_name"] = init.server_info.name
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                summary["discovered"] = names
                result = await session.call_tool(tool_code, arguments or {})
                summary["call_text"] = " ".join(
                    part.text for part in result.content if hasattr(part, "text")
                )
                summary["call_is_error"] = bool(result.is_error)
                summary["structured"] = result.structuredContent
    finally:
        await http_client.aclose()
    return summary


async def _latest_trace_id(client_code: str) -> str | None:
    """查询调试客户端最近一条 MCP Trace（无则返回 None）。"""
    async with database.async_session_factory() as session:
        client = await session.scalar(
            select(McpClient).where(McpClient.client_code == client_code)
        )
        if client is None:
            return None
        event = await session.scalar(
            select(RuntimeTraceLog)
            .where(
                RuntimeTraceLog.channel == "mcp",
                RuntimeTraceLog.mcp_client_id == client.id,
            )
            .order_by(RuntimeTraceLog.occurred_at.desc())
            .limit(1)
        )
        return event.trace_id if event is not None else None
