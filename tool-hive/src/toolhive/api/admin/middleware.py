"""管理侧 API 中间件：会话加载、CSRF 校验。"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from toolhive.services.security.csrf import verify_csrf_token
from toolhive.services.security.session import get_session

logger = logging.getLogger(__name__)

# 只读方法（不校验 CSRF）
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# 无需 CSRF 校验的公开路径前缀
_CSRF_SKIP_PREFIXES = (
    "/auth/login",
    "/auth/captcha/challenge",
    "/auth/csrf-token",
)


class SessionMiddleware(BaseHTTPMiddleware):
    """从共享存储加载会话，附加到 request.state。

    仅在会话有效时放行；会话无效或超时返回 401。
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        session_id = request.cookies.get("toolhive_session")
        if session_id:
            session = await get_session(session_id)
            if session:
                request.state.session = session
                request.state.account_id = session.account_id
                request.state.username = session.username
            else:
                request.state.session = None
        else:
            request.state.session = None

        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """非只读请求校验 CSRF Token + Origin/Referer。

    公开接口（login、csrf-token）自动跳过。
    """

    def _skip_csrf(self, path: str) -> bool:
        return any(path.startswith(p) for p in _CSRF_SKIP_PREFIXES)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 只读方法放行
        if request.method.upper() in _READ_METHODS:
            return await call_next(request)

        # 公开接口放行（login、csrf-token 等）
        if self._skip_csrf(request.url.path):
            return await call_next(request)

        session = getattr(request.state, "session", None)
        if session is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "未认证"},
            )

        # 校验 CSRF Token
        csrf_header = request.headers.get("X-CSRF-Token", "")
        if not csrf_header or not verify_csrf_token(session.session_id, csrf_header):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF 校验失败"},
            )

        return await call_next(request)
