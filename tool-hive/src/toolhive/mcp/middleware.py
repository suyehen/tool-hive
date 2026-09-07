"""宿主侧 MCP 鉴权中间件（阶段 2 定稿，替代 SDK 原生 TokenVerifier）。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from toolhive.infrastructure import database
from toolhive.mcp.auth import (
    McpAuthError,
    McpAuthService,
    current_mcp_identity,
)
from toolhive.mcp.server import MCP_MOUNT_PATH
from toolhive.runtime.tracing.service import TraceService


class McpAuthMiddleware(BaseHTTPMiddleware):
    """拦截 MCP 端点请求，在协议解析前完成 Bearer Token 完整认证。"""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(MCP_MOUNT_PATH):
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        source_ip = getattr(request.state, "client_ip", "") or (
            request.client.host if request.client else ""
        )
        async with database.async_session_factory() as session:
            service = McpAuthService(session, source_ip)
            try:
                identity = await service.authenticate(token)
            except McpAuthError as exc:
                await TraceService.log_event(
                    trace_id=getattr(request.state, "trace_id", None) or "",
                    action="runtime.auth",
                    status="failure",
                    error_code=exc.code,
                    summary={"path": request.url.path},
                    source_ip=source_ip,
                    channel="mcp",
                )
                return JSONResponse(
                    status_code=exc.http_status,
                    content={"code": exc.code, "message": exc.message},
                    headers={
                        "WWW-Authenticate": 'Bearer error="invalid_token"',
                    },
                )
        request.state.mcp_identity = identity
        token = current_mcp_identity.set(identity)
        try:
            await TraceService.log_event(
                trace_id=getattr(request.state, "trace_id", None) or "",
                action="runtime.auth",
                status="success",
                summary={
                    "client_code": identity.client.client_code,
                    "path": request.url.path,
                },
                source_ip=source_ip,
                channel="mcp",
                mcp_client_id=identity.client.id,
            )
            return await call_next(request)
        finally:
            current_mcp_identity.reset(token)
