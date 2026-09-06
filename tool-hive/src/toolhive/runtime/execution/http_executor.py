"""受控 HTTP Provider 执行器：SSRF、TLS、超时、限制、重试与熔断。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from toolhive.config import RuntimeSecuritySettings
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PROVIDER_ERROR,
    RUNTIME_PROVIDER_TIMEOUT,
    RuntimeApiError,
)
from toolhive.runtime.execution.gateway import ProviderExecutor
from toolhive.runtime.execution.outbound import (
    build_outbound_request,
    pin_outbound_url,
    resolve_host,
    validate_resolved_addresses,
)

logger = logging.getLogger(__name__)

_READ_METHODS = ("GET",)
_PROVIDER_CIRCUIT_FAIL_PREFIX = "toolhive:provider_circuit:fail:"
_PROVIDER_CIRCUIT_OPEN_PREFIX = "toolhive:provider_circuit:open:"


class HttpExecutor(ProviderExecutor):
    """外部 HTTP 目标执行器（一期仅 https + 固定映射）。"""

    provider_type = "http"

    def __init__(self, redis, security: RuntimeSecuritySettings):
        self._redis = redis
        self._security = security

    async def execute(
        self,
        binding: CatalogExecutionBinding,
        provider: CatalogProvider,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """执行受控出站请求并返回标准化 JSON 结果。"""
        await self._check_circuit(binding.provider_id)
        request = build_outbound_request(provider, binding, arguments)
        self._validate_outbound_request(request)
        # SSRF：DNS 全量解析后校验全部地址（任一不合格即整请求拒绝）
        addresses = resolve_host(request.host)
        validate_resolved_addresses(
            addresses,
            (provider.target_security_config or {}).get("allowed_cidrs") or [],
        )
        # 固定连接已校验的解析地址，避免 DNS 二次解析产生的 TOCTOU
        connect_address = str(addresses[0]) if addresses else request.host

        # 读操作（GET）瞬时错误有限重试；写操作不盲目重试；
        # 历史脏数据中的负 retry_max 一律按 0 处理，避免空重试循环
        retry_max = binding.retry_max
        if retry_max is None or retry_max < 0:
            retry_max = 0
        max_attempts = 1
        if binding.method in _READ_METHODS:
            max_attempts += retry_max
        last_error: RuntimeApiError | None = None
        response: httpx.Response | None = None
        for attempt in range(max_attempts):
            try:
                response = await self._send(request, connect_address)
                break
            except RuntimeApiError as exc:
                last_error = exc
                retryable = (
                    binding.method in _READ_METHODS
                    and exc.code == RUNTIME_PROVIDER_TIMEOUT
                    and attempt < max_attempts - 1
                )
                if not retryable:
                    await self._record_failure(binding.provider_id)
                    raise
        if response is None:
            await self._record_failure(binding.provider_id)
            if last_error is not None:
                raise last_error
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标请求未返回响应", 502,
            )

        # 目标错误与响应标准化
        if response.status_code >= 400:
            await self._record_failure(binding.provider_id)
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                f"目标返回 HTTP {response.status_code}",
                502,
            )
        try:
            result = self._normalize_response(response)
        except RuntimeApiError:
            # JSON 非法、响应超限、非对象等目标侧协议错误均计入熔断统计
            await self._record_failure(binding.provider_id)
            raise
        await self._record_success(binding.provider_id)
        return result

    async def _send(self, request, connect_address: str) -> httpx.Response:
        """发起 HTTPS 请求：固定已校验 IP、流式限制响应体、不跟随重定向。"""
        total = request.timeout_seconds
        connect_timeout = min(self._security.provider_connect_timeout_seconds, total)
        timeout = httpx.Timeout(
            total,
            connect=connect_timeout,
            read=self._security.provider_read_timeout_seconds,
        )
        pinned_url, host_headers = pin_outbound_url(
            request.url, connect_address, request.host,
        )
        headers = {**request.headers, **host_headers}
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                verify=True,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    method=request.method,
                    url=pinned_url,
                    headers=headers,
                    params=request.query_params or None,
                    json=request.json_body,
                    extensions={"sni_hostname": request.host},
                ) as response:
                    # Header 数量超限时立即中止，不读取响应体
                    if len(response.headers) > self._security.provider_max_header_count:
                        raise RuntimeApiError(
                            RUNTIME_PROVIDER_ERROR,
                            "目标响应 Header 数量超限",
                            502,
                        )
                    content, total_read = [], 0
                    async for chunk in response.aiter_bytes():
                        total_read += len(chunk)
                        if total_read > self._security.provider_max_response_bytes:
                            raise RuntimeApiError(
                                RUNTIME_PROVIDER_ERROR,
                                "目标响应体超过大小上限",
                                502,
                            )
                        content.append(chunk)
                    return httpx.Response(
                        status_code=response.status_code,
                        headers=response.headers,
                        content=b"".join(content),
                        request=response.request,
                        history=response.history,
                    )
        except httpx.TimeoutException as exc:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_TIMEOUT, "目标请求超时", 504,
            ) from exc
        except httpx.HTTPError as exc:
            # TODO: 此处明文记录完整 URL（含查询串），后续可调整为掩码方案（脱敏）
            logger.error("provider http error url=%s error=%s", request.url, exc)
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标请求失败", 502,
            ) from exc

    def _validate_outbound_request(self, request) -> None:
        """出站前校验请求体大小与 Header 数量，超限直接拒绝。"""
        if len(request.headers) > self._security.provider_max_request_header_count:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                "出站请求 Header 数量超过上限",
                502,
            )
        body_bytes = json.dumps(
            request.json_body or {},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body_bytes) > self._security.provider_max_request_bytes:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                "出站请求体超过大小上限",
                502,
            )

    def _normalize_response(self, response: httpx.Response) -> dict[str, Any]:
        """响应限制与 JSON 标准化。"""
        if len(response.headers) > self._security.provider_max_header_count:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标响应 Header 数量超限", 502,
            )
        content = response.content
        if len(content) > self._security.provider_max_response_bytes:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标响应体超过大小上限", 502,
            )
        try:
            data = response.json()
        except ValueError:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标响应不是合法 JSON", 502,
            )
        if not isinstance(data, dict):
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "目标响应必须是 JSON 对象", 502,
            )
        return data

    async def _check_circuit(self, provider_id: str) -> None:
        """Provider 目标熔断检查。"""
        opened = await self._redis.exists(
            f"{_PROVIDER_CIRCUIT_OPEN_PREFIX}{provider_id}"
        )
        if opened:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR, "Provider 目标熔断打开，请求被拒绝", 503,
            )

    async def _record_failure(self, provider_id: str) -> None:
        """记录目标失败；连续失败达到阈值时打开熔断。"""
        key = f"{_PROVIDER_CIRCUIT_FAIL_PREFIX}{provider_id}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(
                key, self._security.circuit_breaker_window_seconds,
            )
        if count >= self._security.circuit_breaker_failure_threshold:
            await self._redis.set(
                f"{_PROVIDER_CIRCUIT_OPEN_PREFIX}{provider_id}",
                "1",
                ex=self._security.circuit_breaker_open_seconds,
            )
            logger.error(
                "provider circuit opened provider=%s failures=%s",
                provider_id, count,
            )

    async def _record_success(self, provider_id: str) -> None:
        """请求成功时重置目标失败计数。"""
        await self._redis.delete(
            f"{_PROVIDER_CIRCUIT_FAIL_PREFIX}{provider_id}"
        )
