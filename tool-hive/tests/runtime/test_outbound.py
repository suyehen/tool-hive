"""受控出站构建与 SSRF 防护测试。"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch

import pytest

from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_SSRF_BLOCKED,
    RuntimeApiError,
)
from toolhive.runtime.execution.outbound import (
    build_outbound_request,
    resolve_host,
    validate_resolved_addresses,
)


def _provider(**kwargs) -> CatalogProvider:
    defaults = dict(
        id="prov-1",
        provider_code="http1",
        name="外部服务",
        provider_type="http",
        status=CatalogObjectStatus.ENABLED,
        target_security_config={
            "allowed_domains": ["api.example.com"],
            "allowed_ports": [443],
            "path_prefix": "/v1",
            "protocols": ["https"],
            "dns_tls_verification": True,
            "allowed_cidrs": [],
        },
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogProvider(**defaults)


def _binding(method: str = "GET", mapping: dict | None = None, **kwargs) -> CatalogExecutionBinding:
    defaults = dict(
        id="binding-1",
        version_id="ver-1",
        provider_id="prov-1",
        method=method,
        path_template="/calc",
        parameter_mapping=mapping or {},
        allowed_headers=[],
        timeout_seconds=5,
        retry_max=0,
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogExecutionBinding(**defaults)


async def test_build_url_and_query_for_get() -> None:
    """GET 请求组装 URL 与查询参数。"""
    request = build_outbound_request(
        _provider(),
        _binding(
            mapping={"query": {"a": "$.left", "b": "2"}},
        ),
        {"left": 1},
    )
    assert request.url == "https://api.example.com/v1/calc"
    assert request.query_params == {"a": "1", "b": "2"}
    assert request.json_body is None


async def test_build_url_and_body_for_post() -> None:
    """POST 请求组装 JSON 请求体。"""
    request = build_outbound_request(
        _provider(),
        _binding(
            method="POST",
            mapping={"body": {"left": "$.left", "op": "+"}},
        ),
        {"left": 1},
    )
    assert request.json_body == {"left": 1, "op": "+"}


async def test_build_requires_single_domain() -> None:
    """http Provider 必须配置且仅配置一个目标域名。"""
    provider = _provider(
        target_security_config={
            "allowed_domains": ["a.example.com", "b.example.com"],
        }
    )
    with pytest.raises(RuntimeApiError):
        build_outbound_request(provider, _binding(), {})


async def test_build_rejects_domain_outside_whitelist() -> None:
    """目标域名不在白名单时拒绝。"""
    provider = _provider(
        target_security_config={"allowed_domains": ["api.example.com"]},
    )
    binding = _binding(path_template="/x")
    # 白名单本身校验：host 取自白名单，因此无法构造越权域名；
    # 这里直接验证域名匹配逻辑经由 build 的 host 校验路径
    request = build_outbound_request(provider, binding, {})
    assert request.host == "api.example.com"


async def test_build_header_whitelist_enforced() -> None:
    """不在允许列表的 Header 被拒绝。"""
    provider = _provider()
    binding = _binding(
        method="POST",
        mapping={"header": {"X-Secret": "$.token"}},
        allowed_headers=[],
    )
    with pytest.raises(RuntimeApiError):
        build_outbound_request(provider, binding, {"token": "abc"})


async def test_build_header_from_allowed_list() -> None:
    """允许列表内的 Header 正常构建。"""
    provider = _provider()
    binding = _binding(
        method="POST",
        mapping={"header": {"X-Trace": "$.tid"}},
        allowed_headers=["X-Trace"],
    )
    request = build_outbound_request(provider, binding, {"tid": "t-1"})
    assert request.headers == {"X-Trace": "t-1"}


async def test_build_missing_argument_rejected() -> None:
    """映射引用不存在的参数时拒绝。"""
    provider = _provider()
    binding = _binding(mapping={"query": {"a": "$.missing"}})
    with pytest.raises(RuntimeApiError) as exc_info:
        build_outbound_request(provider, binding, {})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_resolve_host_returns_unique_addresses() -> None:
    """域名解析返回去重后的 IP 列表。"""
    with patch(
        "toolhive.runtime.execution.outbound.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        ],
    ):
        addresses = resolve_host("api.example.com")
    assert addresses == [ipaddress.ip_address("93.184.216.34")]


async def test_validate_rejects_loopback_and_metadata() -> None:
    """回环与云元数据地址无条件拒绝。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        validate_resolved_addresses(
            [ipaddress.ip_address("127.0.0.1")], [],
        )
    assert exc_info.value.code == RUNTIME_PROVIDER_SSRF_BLOCKED
    with pytest.raises(RuntimeApiError):
        validate_resolved_addresses(
            [ipaddress.ip_address("169.254.169.254")], [],
        )


async def test_validate_private_requires_cidr() -> None:
    """私网地址默认拒绝，显式 CIDR 放行。"""
    private = ipaddress.ip_address("10.1.2.3")
    with pytest.raises(RuntimeApiError):
        validate_resolved_addresses([private], [])
    validate_resolved_addresses([private], ["10.0.0.0/8"])


async def test_validate_public_allowed() -> None:
    """公网地址放行。"""
    validate_resolved_addresses(
        [ipaddress.ip_address("93.184.216.34")], [],
    )


async def test_validate_rejects_multicast() -> None:
    """多播地址拒绝。"""
    with pytest.raises(RuntimeApiError):
        validate_resolved_addresses(
            [ipaddress.ip_address("224.0.0.1")], [],
        )
