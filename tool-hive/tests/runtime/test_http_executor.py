"""受控 HTTP Provider 执行器测试。"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PROVIDER_ERROR,
    RUNTIME_PROVIDER_TIMEOUT,
    RuntimeApiError,
)
from toolhive.runtime.execution.http_executor import HttpExecutor


def _provider() -> CatalogProvider:
    return CatalogProvider(
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


def _binding(method: str = "GET", retry_max: int = 0) -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1",
        version_id="ver-1",
        provider_id="prov-1",
        method=method,
        path_template="/calc",
        parameter_mapping={},
        allowed_headers=[],
        timeout_seconds=5,
        retry_max=retry_max,
        row_version=0,
    )


def _security(**kwargs) -> RuntimeSecuritySettings:
    defaults = dict(
        circuit_breaker_failure_threshold=3,
        circuit_breaker_window_seconds=60,
        circuit_breaker_open_seconds=30,
        provider_max_response_bytes=1024,
        provider_max_header_count=10,
        provider_connect_timeout_seconds=5,
    )
    defaults.update(kwargs)
    return RuntimeSecuritySettings(**defaults)


def _redis() -> AsyncMock:
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.delete = AsyncMock()
    return redis


def _patch_send(response_or_error) -> None:
    """占位：测试直接覆盖 executor._send。"""


@contextmanager
def _bypass_dns():
    """跳过真实 DNS 解析与地址校验（由 outbound 测试覆盖）。"""
    with (
        patch(
            "toolhive.runtime.execution.http_executor.resolve_host",
            return_value=[],
        ),
        patch(
            "toolhive.runtime.execution.http_executor.validate_resolved_addresses",
            new=MagicMock(),
        ),
    ):
        yield


async def test_http_success_returns_json() -> None:
    """成功调用返回标准化 JSON 结果。"""
    executor = HttpExecutor(_redis(), _security())
    executor._send = AsyncMock(
        return_value=httpx.Response(200, json={"ok": True}),
    )
    with _bypass_dns():
        result = await executor.execute(_binding(), _provider(), {})
    assert result == {"ok": True}


async def test_http_target_5xx_rejected() -> None:
    """目标 5xx 返回 Provider 错误。"""
    redis = _redis()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    executor = HttpExecutor(redis, _security())
    executor._send = AsyncMock(return_value=httpx.Response(500, text="boom"))
    with _bypass_dns():
        with pytest.raises(RuntimeApiError) as exc_info:
            await executor.execute(_binding(), _provider(), {})
    assert exc_info.value.code == RUNTIME_PROVIDER_ERROR


async def test_http_non_json_response_rejected() -> None:
    """非 JSON 响应被拒绝。"""
    executor = HttpExecutor(_redis(), _security())
    executor._send = AsyncMock(return_value=httpx.Response(200, text="not json"))
    with _bypass_dns():
        with pytest.raises(RuntimeApiError) as exc_info:
            await executor.execute(_binding(), _provider(), {})
    assert exc_info.value.code == RUNTIME_PROVIDER_ERROR


async def test_http_response_size_limited() -> None:
    """响应体超过大小上限被拒绝。"""
    executor = HttpExecutor(
        _redis(), _security(provider_max_response_bytes=4),
    )
    executor._send = AsyncMock(
        return_value=httpx.Response(200, json={"data": "x" * 100}),
    )
    with _bypass_dns():
        with pytest.raises(RuntimeApiError):
            await executor.execute(_binding(), _provider(), {})


async def test_read_retry_on_transient_timeout() -> None:
    """读操作瞬时超时按 retry_max 重试后成功。"""
    executor = HttpExecutor(_redis(), _security())
    executor._send = AsyncMock(
        side_effect=[
            RuntimeApiError(RUNTIME_PROVIDER_TIMEOUT, "超时", 504),
            RuntimeApiError(RUNTIME_PROVIDER_TIMEOUT, "超时", 504),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with _bypass_dns():
        result = await executor.execute(_binding(retry_max=2), _provider(), {})
    assert result == {"ok": True}
    assert executor._send.await_count == 3


async def test_write_does_not_retry() -> None:
    """写操作超时不做盲目重试。"""
    redis = _redis()
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    executor = HttpExecutor(redis, _security())
    executor._send = AsyncMock(
        side_effect=RuntimeApiError(RUNTIME_PROVIDER_TIMEOUT, "超时", 504),
    )
    with _bypass_dns():
        with pytest.raises(RuntimeApiError):
            await executor.execute(_binding(method="POST", retry_max=2), _provider(), {})
    assert executor._send.await_count == 1


async def test_circuit_open_rejects_before_send() -> None:
    """Provider 熔断打开时直接拒绝。"""
    redis = _redis()
    redis.exists = AsyncMock(return_value=1)
    executor = HttpExecutor(redis, _security())
    executor._send = AsyncMock()
    with _bypass_dns():
        with pytest.raises(RuntimeApiError):
            await executor.execute(_binding(), _provider(), {})
    executor._send.assert_not_awaited()


async def test_record_failure_opens_circuit_after_threshold() -> None:
    """连续失败达到阈值打开熔断。"""
    redis = _redis()
    redis.incr = AsyncMock(side_effect=[1, 2, 3])
    redis.expire = AsyncMock()
    redis.set = AsyncMock()
    executor = HttpExecutor(redis, _security())
    for _ in range(3):
        await executor._record_failure("prov-1")
    redis.set.assert_awaited_once()
