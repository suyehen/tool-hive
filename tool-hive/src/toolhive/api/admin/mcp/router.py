"""MCP 接入管理 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.deps import require_operation
from toolhive.api.admin.mcp.schemas import (
    AddIpRuleRequest,
    CallRecordListResponse,
    ConsoleDebugRequest,
    ConsoleDebugResponse,
    CreateMcpClientRequest,
    ExposedToolResponse,
    IpRuleResponse,
    IpRuleStatusUpdateRequest,
    IssueTokenResponse,
    McpClientListResponse,
    McpClientResponse,
    ReplaceScopesRequest,
    ScopeResponse,
    ServerConfigResponse,
    StatusRequest,
    TraceDetailResponse,
    TraceEventResponse,
    UpdateMcpClientRequest,
    UpdateServerConfigRequest,
)
from toolhive.core.enums import IPRuleStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.mcp.console import run_console_session
from toolhive.services.mcp_client_service import McpClientService
from toolhive.services.mcp_exposed_tool_service import McpExposedToolService
from toolhive.services.mcp_server_config_service import McpServerConfigService
from toolhive.services.mcp_trace_query_service import McpTraceQueryService
from toolhive.services.role_service import RoleService

router = APIRouter(prefix="/mcp", tags=["MCP 接入"])


def _to_client_response(client) -> McpClientResponse:
    return McpClientResponse(
        id=client.id,
        client_code=client.client_code,
        name=client.name,
        description=client.description,
        status=client.status,
        deactivated_reason=client.deactivated_reason,
        row_version=client.row_version,
        created_at=client.create_time,
        updated_at=client.update_time,
    )


def _to_server_response(config) -> ServerConfigResponse:
    return ServerConfigResponse(
        id=config.id,
        server_name=config.server_name,
        description=config.description,
        enabled=config.enabled,
        endpoint_path=config.endpoint_path,
        allowed_hosts=config.allowed_hosts or [],
        protocol_versions=config.protocol_versions,
        row_version=config.row_version,
        created_at=config.create_time,
        updated_at=config.update_time,
    )


def _handle_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _to_trace_event_response(event) -> TraceEventResponse:
    return TraceEventResponse(
        id=event.id,
        trace_id=event.trace_id,
        action=event.action,
        status=event.status,
        error_code=event.error_code,
        summary=event.summary,
        source_ip=event.source_ip,
        mcp_client_id=event.mcp_client_id,
        occurred_at=event.occurred_at,
    )


# ── Server 接入配置 ──


@router.get("/server-config", response_model=ServerConfigResponse)
async def get_server_config(
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_SERVER_VIEW)),
):
    """查询 MCP Server 接入配置。"""
    return _to_server_response(await McpServerConfigService(db).get_config())


@router.put("/server-config", response_model=ServerConfigResponse)
async def update_server_config(
    body: UpdateServerConfigRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_SERVER_CONFIG)),
):
    """更新 MCP Server 接入配置。"""
    svc = McpServerConfigService(db)
    try:
        config = await svc.update_config(
            server_name=body.server_name,
            description=body.description,
            enabled=body.enabled,
            endpoint_path=body.endpoint_path,
            allowed_hosts=body.allowed_hosts,
            protocol_versions=body.protocol_versions,
            expected_row_version=body.row_version,
        )
    except (ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return _to_server_response(config)


# ── MCP 客户端 ──


@router.get("/clients", response_model=McpClientListResponse)
async def list_clients(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_VIEW)),
):
    """查询 MCP 客户端列表。"""
    items, total = await McpClientService(db).list_clients(
        offset=offset, limit=limit, keyword=keyword, status=status,
    )
    return McpClientListResponse(
        items=[_to_client_response(item) for item in items], total=total,
    )


@router.post("/clients", response_model=McpClientResponse, status_code=201)
async def create_client(
    body: CreateMcpClientRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """创建 MCP 客户端（草稿状态）。"""
    svc = McpClientService(db)
    try:
        client = await svc.create_client(
            name=body.name, description=body.description,
        )
    except ValidationError as exc:
        raise _handle_service_error(exc)
    return _to_client_response(client)


@router.get("/clients/{client_code}", response_model=McpClientResponse)
async def get_client(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_VIEW)),
):
    """查询 MCP 客户端详情。"""
    svc = McpClientService(db)
    try:
        return _to_client_response(await svc.get_by_client_code(client_code))
    except NotFoundError as exc:
        raise _handle_service_error(exc)


@router.patch("/clients/{client_code}", response_model=McpClientResponse)
async def update_client(
    client_code: str,
    body: UpdateMcpClientRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """更新 MCP 客户端资料。"""
    svc = McpClientService(db)
    try:
        client = await svc.update_client(
            client_code,
            name=body.name,
            description=body.description,
            expected_row_version=body.row_version,
        )
    except (NotFoundError, ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return _to_client_response(client)


@router.post("/clients/{client_code}/enable", response_model=McpClientResponse)
async def enable_client(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """启用 MCP 客户端（需令牌与来源 IP 规则齐备）。"""
    svc = McpClientService(db)
    try:
        return _to_client_response(await svc.enable(client_code))
    except (NotFoundError, ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)


@router.post("/clients/{client_code}/disable", response_model=McpClientResponse)
async def disable_client(
    client_code: str,
    body: StatusRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """停用 MCP 客户端。"""
    svc = McpClientService(db)
    try:
        return _to_client_response(
            await svc.disable(client_code, body.reason if body else None)
        )
    except (NotFoundError, ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)


@router.post("/clients/{client_code}/revive", response_model=McpClientResponse)
async def revive_client(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """恢复已注销客户端为停用状态。"""
    svc = McpClientService(db)
    try:
        return _to_client_response(await svc.revive(client_code))
    except (NotFoundError, ConflictError) as exc:
        raise _handle_service_error(exc)


@router.post("/clients/{client_code}/revoke", response_model=McpClientResponse)
async def revoke_client(
    client_code: str,
    body: StatusRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """注销 MCP 客户端并吊销其令牌。"""
    svc = McpClientService(db)
    try:
        return _to_client_response(
            await svc.revoke(client_code, body.reason if body else None)
        )
    except (NotFoundError, ConflictError) as exc:
        raise _handle_service_error(exc)


# ── 令牌 ──


@router.post("/clients/{client_code}/token", response_model=IssueTokenResponse)
async def issue_token(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """签发 MCP 客户端访问令牌（明文仅本次返回）。"""
    svc = McpClientService(db)
    try:
        record, token = await svc.issue_token(client_code)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return IssueTokenResponse(
        token=token, token_id=record.id, client_code=client_code,
    )


@router.post("/clients/{client_code}/token/revoke")
async def revoke_token(
    client_code: str,
    body: StatusRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """吊销 MCP 客户端当前 ACTIVE 令牌。"""
    svc = McpClientService(db)
    try:
        await svc.revoke_token(client_code, body.reason if body else None)
    except (NotFoundError, ConflictError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return {"detail": "令牌已吊销"}


# ── 来源 IP 规则 ──


@router.get("/clients/{client_code}/ip-rules", response_model=list[IpRuleResponse])
async def list_ip_rules(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_VIEW)),
):
    """查询 MCP 客户端来源 IP 规则。"""
    svc = McpClientService(db)
    try:
        await svc.get_by_client_code(client_code)
        rules = await svc.list_ip_rules(client_code)
    except NotFoundError as exc:
        raise _handle_service_error(exc)
    return [
        IpRuleResponse(
            id=rule.id,
            client_id=rule.client_id,
            ip_cidr=rule.ip_cidr,
            description=rule.description,
            status=rule.status,
            row_version=rule.row_version,
            created_at=rule.create_time,
        )
        for rule in rules
    ]


@router.post(
    "/clients/{client_code}/ip-rules",
    response_model=IpRuleResponse,
    status_code=201,
)
async def add_ip_rule(
    client_code: str,
    body: AddIpRuleRequest,
    db: AsyncSession = Depends(get_db),
    account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """新增 MCP 客户端来源 IP 规则；通配规则需额外操作码。"""
    if body.ip_cidr.strip() == "*":
        role_svc = RoleService(db)
        if not await role_svc.check_operation(
            account.id, OperationCode.MCP_CLIENT_ALLOW_ANY_IP
        ):
            raise HTTPException(
                status_code=403,
                detail="缺少操作项: mcp_client:allow_any_ip",
            )
    svc = McpClientService(db)
    try:
        rule = await svc.add_ip_rule(
            client_code,
            ip_cidr=body.ip_cidr,
            description=body.description,
        )
    except (NotFoundError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return IpRuleResponse(
        id=rule.id,
        client_id=rule.client_id,
        ip_cidr=rule.ip_cidr,
        description=rule.description,
        status=rule.status,
        row_version=rule.row_version,
        created_at=rule.create_time,
    )


@router.patch("/ip-rules/{rule_id}/status")
async def update_ip_rule_status(
    rule_id: str,
    body: IpRuleStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_MANAGE)),
):
    """启停来源 IP 规则。"""
    svc = McpClientService(db)
    try:
        status = IPRuleStatus.ACTIVE if body.enabled else IPRuleStatus.DISABLED
        await svc.update_ip_rule_status(rule_id, status)
    except (NotFoundError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return {"detail": "操作成功"}


# ── 授权范围 ──


@router.get("/clients/{client_code}/scopes", response_model=list[ScopeResponse])
async def list_scopes(
    client_code: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_AUTH_VIEW)),
):
    """查询 MCP 客户端授权范围（含 Catalog 引用状态）。"""
    svc = McpClientService(db)
    try:
        rows = await svc.list_scopes_with_reference(client_code)
    except NotFoundError as exc:
        raise _handle_service_error(exc)
    return [
        ScopeResponse(
            id=row["id"],
            client_id=row["client_id"],
            scope_type=row["scope_type"],
            scope_code=row["scope_code"],
            status=row["status"],
            row_version=row["row_version"],
            created_at=row["created_at"],
            reference_exists=row["reference_exists"],
            reference_archived=row["reference_archived"],
        )
        for row in rows
    ]


@router.put(
    "/clients/{client_code}/scopes", response_model=list[ScopeResponse],
)
async def replace_scopes(
    client_code: str,
    body: ReplaceScopesRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_AUTH_MANAGE)),
):
    """全量替换 MCP 客户端授权范围。"""
    svc = McpClientService(db)
    try:
        scopes = await svc.replace_scopes(
            client_code,
            items=[item.model_dump() for item in body.items],
        )
    except (NotFoundError, ValidationError) as exc:
        raise _handle_service_error(exc)
    return [
        ScopeResponse(
            id=scope.id,
            client_id=scope.client_id,
            scope_type=scope.scope_type,
            scope_code=scope.scope_code,
            status=scope.status,
            row_version=scope.row_version,
            created_at=scope.create_time,
        )
        for scope in scopes
    ]


# ── 暴露工具与调用记录 ──


@router.get("/exposed-tools", response_model=list[ExposedToolResponse])
async def list_exposed_tools(
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_CLIENT_VIEW)),
):
    """只读查询 MCP 可发现工具集合。"""
    items = await McpExposedToolService(db).list_exposed()
    return [
        ExposedToolResponse(
            id=item.id,
            full_code=item.full_code,
            name=item.name,
            risk_level=item.risk_level,
            status=item.status,
            mcp_enabled=item.mcp_enabled,
            version=item.version,
        )
        for item in items
    ]


@router.get("/call-records", response_model=CallRecordListResponse)
async def list_call_records(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_TRACE_VIEW)),
):
    """分页查询 MCP 调用记录（每个 trace 一条摘要）。"""
    items, total = await McpTraceQueryService(db).list_records(
        offset=offset, limit=limit, status=status, client_id=client_id,
    )
    return CallRecordListResponse(
        items=[_to_trace_event_response(item) for item in items], total=total,
    )


@router.get("/call-records/{trace_id}", response_model=TraceDetailResponse)
async def get_call_record_detail(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.MCP_TRACE_VIEW)),
):
    """查询单个 MCP trace 的完整事件链。"""
    events = await McpTraceQueryService(db).get_events(trace_id)
    return TraceDetailResponse(
        trace_id=trace_id,
        events=[_to_trace_event_response(event) for event in events],
    )


@router.post("/test-debug", response_model=ConsoleDebugResponse)
async def run_test_debug(
    body: ConsoleDebugRequest,
    _account=Depends(require_operation(OperationCode.MCP_TEST_RUN)),
):
    """运行一次 MCP 协议级调试会话。"""
    result = await run_console_session(
        body.tool_code, body.arguments or {},
    )
    return ConsoleDebugResponse(
        ok=result.ok,
        server_name=result.server_name,
        discovered=result.discovered,
        call_text=result.call_text,
        call_is_error=result.call_is_error,
        trace_id=result.trace_id,
        detail=result.detail,
    )
