"""MCP 阶段 0 Spike 测试：SDK 挂载与宿主生命周期协议闭环。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from toolhive.mcp.server import MCP_MOUNT_PATH, get_mcp_app, get_server

_MCP_URL = f"http://127.0.0.1:8000{MCP_MOUNT_PATH}/"


@asynccontextmanager
async def _host_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """宿主应用生命周期：模拟 main.py 中进入 MCP session_manager。"""
    async with get_server().session_manager.run():
        yield


def _build_host_app() -> FastAPI:
    """构造仅含 MCP 挂载的最小 FastAPI 宿主（与 main.py 挂载方式一致）。"""
    host = FastAPI(lifespan=_host_lifespan)
    host.mount(MCP_MOUNT_PATH, get_mcp_app())
    return host


def test_mount_path_is_exposed() -> None:
    """宿主已挂载 MCP 子应用且路径配置为完整公开路径。"""
    host = _build_host_app()
    # 直接验证子应用路由：/ 是 streamable_http_path="/" 的端点，经 /mcp 挂载后公开为 /mcp
    routes = [route.path for route in host.routes]
    assert f"{MCP_MOUNT_PATH}/" in routes or MCP_MOUNT_PATH in routes


async def test_mcp_initialize_list_roundtrip() -> None:
    """SDK 挂载后可完成 initialize / tools/list 协议往返。"""
    host = _build_host_app()
    async with get_server().session_manager.run():
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=host),
        )
        try:
            async with streamable_http_client(_MCP_URL, http_client=http_client) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    init = await session.initialize()
                    assert init.server_info.name == "ToolHive"

                    tools = await session.list_tools()
                    assert tools.tools == []
        finally:
            await http_client.aclose()
