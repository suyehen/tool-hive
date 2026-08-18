"""应用入口校验中间件。

A10：ToolHive 只读取可信代理写入的内部 Header：
- 请求对端必须属于配置的可信代理范围（生产），或为回环地址且显式开启开发直连；
- ``/api/admin/**`` 必须携带 ``X-ToolHive-Ingress: admin``；
- 从 ``X-ToolHive-Client-IP`` 解析真实来源 IP，非法值拒绝。
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from toolhive.config import NetworkSettings
from toolhive.core.network import is_loopback, is_trusted_proxy, parse_client_ip

logger = logging.getLogger(__name__)

INGRESS_HEADER = "X-ToolHive-Ingress"
CLIENT_IP_HEADER = "X-ToolHive-Client-IP"
VALID_INGRESS = {"admin", "runtime"}


def _reject(detail: str):
    from starlette.responses import JSONResponse

    return JSONResponse(status_code=403, content={"detail": detail})


class IngressMiddleware(BaseHTTPMiddleware):
    """入口标识与来源 IP 校验中间件。"""

    def __init__(self, app, network: NetworkSettings) -> None:
        super().__init__(app)
        self._network = network

    async def dispatch(self, request: Request, call_next):
        client_host = request.client.host if request.client else ""
        trusted = is_trusted_proxy(client_host, self._network.trusted_proxies)
        ingress = request.headers.get(INGRESS_HEADER, "")

        path = request.url.path
        if path.startswith("/api/admin"):
            required = "admin"
        elif path.startswith("/api/runtime"):
            required = "runtime"
        else:
            required = None

        if required is None:
            # 非 API 路径（如 /health）：只校验来源可信或开发直连
            if trusted:
                request.state.client_ip = client_host
                return await call_next(request)
            if self._network.allow_loopback_direct and is_loopback(client_host):
                request.state.client_ip = client_host
                return await call_next(request)
            return _reject("请求来源不在可信代理范围内")

        direct_loopback = False
        if trusted:
            if ingress not in VALID_INGRESS:
                if self._network.allow_loopback_direct and is_loopback(client_host):
                    direct_loopback = True
                else:
                    return _reject("入口标识缺失或不匹配")
        elif self._network.allow_loopback_direct and is_loopback(client_host):
            direct_loopback = True
        else:
            return _reject("请求来源不在可信代理范围内")

        if direct_loopback:
            logger.warning(
                "ingress: loopback direct mode enabled (dev only) host=%s",
                client_host,
            )
            request.state.client_ip = client_host
        else:
            if ingress != required:
                return _reject("入口标识不匹配")
            client_ip_raw = request.headers.get(CLIENT_IP_HEADER, "")
            client_ip = parse_client_ip(client_ip_raw)
            if client_ip is None:
                return _reject("来源 IP 解析失败")
            request.state.client_ip = client_ip

        return await call_next(request)
