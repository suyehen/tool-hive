"""Provider 健康检查：域名解析 + IP 校验 + HTTPS 可达性。"""

from __future__ import annotations

import httpx

from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.execution.outbound import (
    pin_outbound_url,
    resolve_host,
    validate_resolved_addresses,
)


async def check_provider_health(provider: CatalogProvider) -> dict:
    """返回健康检查结果（builtin 无需出站探测）。"""
    if provider.provider_type != "http":
        return {"healthy": True, "detail": "builtin 类型无需出站健康检查"}
    config = provider.target_security_config or {}
    allowed_domains = config.get("allowed_domains") or []
    if not allowed_domains:
        return {"healthy": False, "detail": "缺少目标域名"}
    host = allowed_domains[0]
    port = (config.get("allowed_ports") or [443])[0]
    try:
        addresses = resolve_host(host)
        validate_resolved_addresses(
            addresses, config.get("allowed_cidrs") or [],
        )
    except Exception as exc:  # 健康检查失败给出可读原因
        return {"healthy": False, "detail": str(exc)}
    # 固定连接已校验地址并通过 SNI 保留域名证书语义
    connect_address = str(addresses[0]) if addresses else host
    pinned_url, host_headers = pin_outbound_url(
        f"https://{host}:{port}/", connect_address, host,
    )
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5, connect=5),
            verify=True,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.get(
                pinned_url,
                headers=host_headers,
                extensions={"sni_hostname": host},
            )
        if 200 <= response.status_code < 400:
            return {"healthy": True, "detail": "目标可达（HTTPS 连接成功）"}
        return {
            "healthy": False,
            "detail": f"目标返回异常状态码: HTTP {response.status_code}",
        }
    except httpx.HTTPError as exc:
        return {"healthy": False, "detail": f"目标不可达: {type(exc).__name__}"}
