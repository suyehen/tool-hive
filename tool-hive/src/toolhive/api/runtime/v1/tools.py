"""运行 API：Resolve / Discover / Execute。"""

from __future__ import annotations

import hashlib
import json
import time

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.deps import get_runtime_security
from toolhive.api.runtime.v1.schemas import (
    DiscoverItem,
    DiscoverRequest,
    DiscoverResponse,
    ExecuteRequest,
    ExecuteResponse,
    ResolveRequest,
    ResolveResponse,
)
from toolhive.config import RuntimeSecuritySettings
from toolhive.infrastructure.database import get_db
from toolhive.infrastructure.redis import get_redis
from toolhive.runtime.confirmations.service import ConfirmationService
from toolhive.runtime.context.schema import parse_tool_context
from toolhive.runtime.context.service import trace_context
from toolhive.runtime.errors import (
    RUNTIME_CONFIRMATION_REQUIRED,
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_ERROR,
    RUNTIME_SCOPE_NOT_ALLOWED,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RUNTIME_TOOL_NOT_FOUND,
    RuntimeApiError,
)
from toolhive.runtime.execution.gateway import BuiltinExecutor, ProviderGateway
from toolhive.runtime.execution.http_executor import HttpExecutor
from toolhive.runtime.execution.idempotency import check_idempotency
from toolhive.runtime.execution.outbound import build_outbound_request
from toolhive.runtime.retrieval.service import RetrievalService
from toolhive.runtime.tool_control.service import CallControlService
from toolhive.runtime.tracing.service import TraceService
from toolhive.runtime.validation.json_schema import JsonSchemaValidator
from toolhive.services.catalog_provider_service import CatalogProviderService

router = APIRouter(prefix="/v1/tools", tags=["runtime-tools"])

_WRITE_METHODS = ("POST", "PUT", "DELETE")


def _decision_http_status(code: str | None) -> int:
    """调用控制错误码 → HTTP 状态（不泄露工具存在性）。"""
    if code in (RUNTIME_TOOL_NOT_FOUND, RUNTIME_TOOL_NOT_AVAILABLE):
        return 404
    if code == RUNTIME_SCOPE_NOT_ALLOWED:
        return 403
    return 400


def _raise_decision(decision) -> None:
    """调用控制拒绝时转换为统一运行错误。"""
    raise RuntimeApiError(
        decision.error_code or RUNTIME_TOOL_NOT_AVAILABLE,
        decision.error_message or "工具不可用",
        _decision_http_status(decision.error_code),
    )


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_tool(
    request: Request,
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """精确解析工具：按范围与发布状态校验，不依赖 Chroma。"""
    identity = request.state.caller_identity
    if body.context is not None:
        context = parse_tool_context(body.context.model_dump())
        await trace_context(
            trace_id=identity.trace_id,
            system_id=identity.system.system_id,
            context=context,
            source_ip=identity.source_ip,
        )
    decision = await CallControlService(db).resolve_tool(
        identity.system.system_id, body.tool_code,
    )
    await TraceService.log_event(
        trace_id=identity.trace_id,
        system_id=identity.system.system_id,
        action="runtime.control",
        status="success" if decision.allowed else "failure",
        error_code=None if decision.allowed else decision.error_code,
        summary={"tool_code": body.tool_code, "decision": "allow" if decision.allowed else "deny"},
        source_ip=identity.source_ip,
    )
    if not decision.allowed:
        _raise_decision(decision)
    assert decision.tool is not None and decision.version is not None
    return ResolveResponse(
        tool_code=decision.tool.full_code,
        name=decision.tool.name,
        description=decision.tool.description,
        risk_level=decision.tool.risk_level,
        version=decision.version.version,
        executable=decision.tool.executable,
        discoverable=True,
        input_schema=decision.version.input_schema or decision.tool.input_schema,
        output_schema=decision.version.output_schema or decision.tool.output_schema,
        trace_id=identity.trace_id,
    )


@router.post("/discover", response_model=DiscoverResponse)
async def discover_tools(
    request: Request,
    body: DiscoverRequest,
    db: AsyncSession = Depends(get_db),
):
    """自然语言关键词发现候选工具（阶段 4 走 PostgreSQL 关键词）。"""
    identity = request.state.caller_identity
    start = time.perf_counter()
    if body.context is not None:
        context = parse_tool_context(body.context.model_dump())
        await trace_context(
            trace_id=identity.trace_id,
            system_id=identity.system.system_id,
            context=context,
            source_ip=identity.source_ip,
        )
    items, degraded = await RetrievalService(db).discover(
        identity.system.system_id, body.query, limit=body.limit,
    )
    await TraceService.log_event(
        trace_id=identity.trace_id,
        system_id=identity.system.system_id,
        action="runtime.retrieval",
        status="success",
        summary={
            # TODO: 此处明文记录 query 原文，后续可调整为掩码方案（脱敏）
            "query": body.query,
            "candidate_count": len(items),
            "degraded": degraded,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        },
        source_ip=identity.source_ip,
    )
    return DiscoverResponse(
        items=[DiscoverItem(**item) for item in items],
        total=len(items),
        limit=body.limit,
        degraded=degraded,
        trace_id=identity.trace_id,
    )


@router.post("/{tool_code}/execute", response_model=ExecuteResponse)
async def execute_tool(
    request: Request,
    tool_code: str,
    body: ExecuteRequest,
    db: AsyncSession = Depends(get_db),
    redis: AsyncRedis = Depends(get_redis),
    runtime_security: RuntimeSecuritySettings = Depends(get_runtime_security),
):
    """二次授权 + 参数校验 + 幂等 + Provider 调用 + 结果标准化。"""
    identity = request.state.caller_identity
    system_id = identity.system.system_id
    start = time.perf_counter()
    if body.context is not None:
        context = parse_tool_context(body.context.model_dump())
        await trace_context(
            trace_id=identity.trace_id,
            system_id=system_id,
            context=context,
            source_ip=identity.source_ip,
        )
    decision = await CallControlService(db).evaluate_executable(
        system_id, tool_code, version=body.version,
    )
    await TraceService.log_event(
        trace_id=identity.trace_id,
        system_id=system_id,
        action="runtime.control",
        status="success" if decision.allowed else "failure",
        error_code=None if decision.allowed else decision.error_code,
        summary={"tool_code": tool_code, "decision": "allow" if decision.allowed else "deny"},
        source_ip=identity.source_ip,
    )
    if not decision.allowed:
        _raise_decision(decision)
    assert decision.tool is not None and decision.version is not None
    if decision.binding is None:
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, "工具版本未配置执行绑定", 400,
        )

    # 高风险 / 写操作二次确认
    if decision.confirmation_required:
        if not body.confirmation_id or not body.confirmation_token:
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_REQUIRED, "该工具需要确认令牌", 403,
            )
        await ConfirmationService(db).verify_confirmation(
            system_id=system_id,
            confirmation_id=body.confirmation_id,
            token=body.confirmation_token,
            trace_id=identity.trace_id,
        )

    # JSON Schema 参数校验（版本级优先，其次工具级）
    input_schema = decision.version.input_schema or decision.tool.input_schema
    JsonSchemaValidator(input_schema).validate(body.arguments)

    # 写操作必须携带幂等键；幂等去重（24h）
    if (
        decision.binding.method in _WRITE_METHODS
        and not body.idempotency_key
    ):
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID, "写操作必须携带幂等键", 400,
        )
    await check_idempotency(system_id, body.idempotency_key, redis)

    # Provider 调用（统一网关，固定映射）
    provider = await CatalogProviderService(db).get_provider(
        decision.binding.provider_id
    )
    gateway = ProviderGateway(
        {
            BuiltinExecutor.provider_type: BuiltinExecutor(),
            HttpExecutor.provider_type: HttpExecutor(redis, runtime_security),
        }
    )
    result = await gateway.execute(
        decision.binding, provider, body.arguments,
    )
    provider_summary: dict = {
        "tool_code": tool_code,
        "provider_type": provider.provider_type,
        "path": decision.binding.path_template,
    }
    if provider.provider_type == "http":
        try:
            outbound = build_outbound_request(
                provider, decision.binding, body.arguments,
            )
            # TODO: 此处明文记录完整查询串，后续可调整为掩码方案（脱敏）
            provider_summary["url"] = outbound.url
        except Exception:
            provider_summary["url"] = None
    await TraceService.log_event(
        trace_id=identity.trace_id,
        system_id=system_id,
        action="runtime.provider",
        status="success",
        summary=provider_summary,
        source_ip=identity.source_ip,
    )
    result_digest = hashlib.sha256(
        json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    await TraceService.log_event(
        trace_id=identity.trace_id,
        system_id=system_id,
        action="runtime.execute",
        status="success",
        summary={
            "tool_code": decision.tool.full_code,
            "version": decision.version.version,
            # TODO: 此处明文记录执行结果，后续可调整为仅存哈希或掩码方案
            "result": result,
            "result_sha256": result_digest,
            "duration_ms": int((time.perf_counter() - start) * 1000),
        },
        source_ip=identity.source_ip,
    )
    return ExecuteResponse(
        tool_code=decision.tool.full_code,
        version=decision.version.version,
        result=result,
        trace_id=identity.trace_id,
    )
