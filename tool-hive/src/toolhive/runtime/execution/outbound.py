"""受控出站构建与 SSRF 防护（域名/端口/协议白名单 + DNS 全量 IP 校验）。"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from typing import Any

from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_ERROR,
    RUNTIME_PROVIDER_SSRF_BLOCKED,
    RuntimeApiError,
)

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 443
# 云元数据等敏感地址（link-local 已覆盖 169.254.0.0/16，这里显式列出备用）
_CLOUD_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}


@dataclass
class OutboundRequest:
    """经过白名单校验的受控出站请求。"""

    url: str
    method: str
    headers: dict[str, str]
    query_params: dict[str, str]
    json_body: dict[str, Any] | None
    timeout_seconds: int
    host: str


def resolve_host(host: str) -> list[ipaddress._BaseAddress]:
    """全量解析域名并返回去重后的 IP 列表（IPv4-mapped IPv6 归一化）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, f"域名解析失败: {host}", 502,
        ) from exc
    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        raw = info[4][0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        if addr not in addresses:
            addresses.append(addr)
    if not addresses:
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, f"域名无解析结果: {host}", 502,
        )
    return addresses


def validate_resolved_addresses(
    addresses: list[ipaddress._BaseAddress],
    allowed_cidrs: list[str] | None,
) -> None:
    """校验解析地址：无条件拒绝回环/链路本地/云元数据/多播/保留地址，私网仅显式 CIDR 放行。"""
    networks = [
        ipaddress.ip_network(cidr.strip(), strict=False)
        for cidr in (allowed_cidrs or [])
        if cidr and cidr.strip()
    ]
    for addr in addresses:
        if addr in _CLOUD_METADATA_ADDRESSES:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_SSRF_BLOCKED,
                f"目标地址命中云元数据地址，已拒绝: {addr}",
                403,
            )
        if (
            addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            raise RuntimeApiError(
                RUNTIME_PROVIDER_SSRF_BLOCKED,
                f"目标地址类型不允许: {addr}",
                403,
            )
        if addr.is_private:
            allowed = any(
                addr.version == network.version and addr in network
                for network in networks
            )
            if not allowed:
                raise RuntimeApiError(
                    RUNTIME_PROVIDER_SSRF_BLOCKED,
                    f"目标私网地址未授权: {addr}",
                    403,
                )


def _domain_allowed(host: str, allowed_domains: list[str]) -> bool:
    """域名白名单：精确匹配或 ``*.`` 子域通配。"""
    normalized = host.lower().rstrip(".")
    for allowed in allowed_domains:
        value = allowed.strip().lower().rstrip(".")
        if not value:
            continue
        if value.startswith("*."):
            suffix = value[1:]
            if normalized.endswith(suffix) and normalized != suffix[1:]:
                return True
        elif normalized == value:
            return True
    return False


def _resolve_argument(arguments: dict[str, Any], path: str) -> Any:
    """按点分路径解析参数。"""
    current: Any = arguments
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"缺少参数: {path}",
                400,
            )
        current = current[part]
    return current


def _map_value(spec: Any, arguments: dict[str, Any]) -> Any:
    """映射值：``$.path`` 引用参数，其余为固定常量。"""
    if isinstance(spec, str) and spec.startswith("$."):
        return _resolve_argument(arguments, spec[2:])
    return spec


def _build_headers(
    binding: CatalogExecutionBinding, arguments: dict[str, Any],
) -> dict[str, str]:
    """仅从绑定允许的 Header 与参数映射构建请求头。"""
    allowed = set(binding.allowed_headers or [])
    mapping = (binding.parameter_mapping or {}).get("header") or {}
    headers: dict[str, str] = {}
    for name, spec in mapping.items():
        if name not in allowed:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                f"Header 不在允许列表: {name}",
                400,
            )
        headers[name] = str(_map_value(spec, arguments))
    return headers


def build_outbound_request(
    provider: CatalogProvider,
    binding: CatalogExecutionBinding,
    arguments: dict[str, Any],
) -> OutboundRequest:
    """按已审核固定映射构建受控出站请求（调用方不能决定 URL/方法/Header）。"""
    config = provider.target_security_config or {}
    allowed_domains = config.get("allowed_domains") or []
    allowed_ports = config.get("allowed_ports") or []
    path_prefix = (config.get("path_prefix") or "").rstrip("/")
    if provider.provider_type != "http":
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, "非 http 类型 Provider 不能构建出站请求", 400,
        )
    if len(allowed_domains) != 1:
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR,
            "http Provider 必须配置且仅配置一个目标域名（一期单目标通道）",
            400,
        )
    host = allowed_domains[0].lower().rstrip(".")
    if not _domain_allowed(host, allowed_domains):
        raise RuntimeApiError(
            RUNTIME_PROVIDER_SSRF_BLOCKED,
            f"目标域名不在白名单: {host}",
            403,
        )
    port = allowed_ports[0] if allowed_ports else _DEFAULT_PORT
    if port != _DEFAULT_PORT:
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = binding.path_template or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"https://{netloc}{path_prefix}{path}"
    mapping = binding.parameter_mapping or {}
    headers = _build_headers(binding, arguments)
    query_params = {
        str(name): str(_map_value(spec, arguments))
        for name, spec in (mapping.get("query") or {}).items()
    }
    body_mapping = mapping.get("body") or {}
    json_body: dict[str, Any] | None = None
    if binding.method != "GET":
        json_body = {
            str(name): _map_value(spec, arguments)
            for name, spec in body_mapping.items()
        }
    return OutboundRequest(
        url=url,
        method=binding.method,
        headers=headers,
        query_params=query_params,
        json_body=json_body,
        timeout_seconds=binding.timeout_seconds or 5,
        host=host,
    )
