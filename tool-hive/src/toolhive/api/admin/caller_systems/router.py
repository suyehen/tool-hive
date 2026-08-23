"""调用系统管理 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.caller_systems.schemas import (
    AddIPRuleRequest,
    AddPublicKeyRequest,
    CallerSystemListResponse,
    CallerSystemResponse,
    CreateCallerSystemRequest,
    EmergencyDisableRequest,
    IPRuleResponse,
    PublicKeyResponse,
    ReplaceToolScopesRequest,
    RuntimePolicyRequest,
    RuntimePolicyResponse,
    StatusRequest,
    ToolScopeResponse,
    UpdateCallerSystemRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.enums import IPRuleStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.caller_system_service import CallerSystemService

router = APIRouter(prefix="/caller-systems", tags=["调用系统"])


def _to_response(cs) -> CallerSystemResponse:
    return CallerSystemResponse(
        id=cs.id,
        system_id=cs.system_id,
        name=cs.name,
        description=cs.description,
        environment=cs.environment,
        belonging_party=cs.belonging_party,
        code=cs.code,
        owner=cs.owner,
        contact=cs.contact,
        owner_email=cs.owner_email,
        tags=cs.get_tags(),
        status=cs.status,
        effective_state=cs.effective_state,
        effective_from=cs.effective_from,
        effective_to=cs.effective_to,
        deactivated_reason=cs.deactivated_reason,
        row_version=cs.row_version,
        created_at=cs.create_time,
        updated_at=cs.update_time,
    )


# ── 调用系统 CRUD ──


@router.get("", response_model=CallerSystemListResponse)
async def list_caller_systems(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_VIEW)),
):
    svc = CallerSystemService(db)
    items, total = await svc.list_systems(
        offset=offset,
        limit=limit,
        keyword=keyword,
        status=status,
        environment=environment,
    )
    return CallerSystemListResponse(
        items=[_to_response(cs) for cs in items], total=total,
    )


@router.post("", response_model=CallerSystemResponse, status_code=201)
async def create_caller_system(
    body: CreateCallerSystemRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_CREATE)),
):
    svc = CallerSystemService(db)
    try:
        cs = await svc.create_draft(
            name=body.name,
            code=body.code,
            environment=body.environment,
            description=body.description,
            belonging_party=body.belonging_party,
            owner=body.owner,
            contact=body.contact,
            owner_email=body.owner_email,
            tags=body.tags,
        effective_from=body.effective_from,
            effective_to=body.effective_to,
        )
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(cs)


@router.get("/{system_id}", response_model=CallerSystemResponse)
async def get_caller_system(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_VIEW)),
):
    svc = CallerSystemService(db)
    try:
        cs = await svc.get_by_system_id(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(cs)


@router.patch("/{system_id}", response_model=CallerSystemResponse)
async def update_caller_system(
    system_id: str,
    body: UpdateCallerSystemRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_EDIT)),
):
    svc = CallerSystemService(db)
    try:
        cs = await svc.update_system(
            system_id,
            name=body.name,
            description=body.description,
            belonging_party=body.belonging_party,
            owner=body.owner,
            contact=body.contact,
            owner_email=body.owner_email,
            tags=body.tags,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(cs)


# ── 生命周期 ──


@router.post("/{system_id}/enable")
async def enable_caller_system(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.enable(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已启用"}


@router.post("/{system_id}/disable")
async def disable_caller_system(
    system_id: str,
    body: StatusRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.disable(system_id, body.reason or "")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已停用"}


@router.post("/{system_id}/revive")
async def revive_caller_system(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.revive(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已恢复"}


@router.post("/{system_id}/revoke")
async def revoke_caller_system(
    system_id: str,
    body: StatusRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.revoke(system_id, body.reason or "")
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已注销"}


# ── 公钥 ──


@router.get("/{system_id}/keys", response_model=list[PublicKeyResponse])
async def list_public_keys(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_VIEW)),
):
    svc = CallerSystemService(db)
    try:
        await svc.get_by_system_id(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    keys = await svc.list_public_keys(system_id)
    return [
        PublicKeyResponse(
            id=k.id, key_id=k.key_id, system_id=k.system_id,
            fingerprint=k.fingerprint, algorithm=k.algorithm, status=k.status,
            effective_from=k.effective_from,
            effective_to=k.effective_to,
            row_version=k.row_version,
            created_at=k.create_time,
        )
        for k in keys
    ]


@router.post("/{system_id}/keys", response_model=PublicKeyResponse, status_code=201)
async def add_public_key(
    system_id: str,
    body: AddPublicKeyRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        key = await svc.add_public_key(
            system_id=system_id,
            public_key=body.public_key,
            algorithm=body.algorithm,
            effective_to=body.effective_to,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return PublicKeyResponse(
        id=key.id, key_id=key.key_id, system_id=key.system_id,
        fingerprint=key.fingerprint, algorithm=key.algorithm, status=key.status,
        effective_from=key.effective_from,
        effective_to=key.effective_to,
        row_version=key.row_version,
        created_at=key.create_time,
    )


@router.post("/keys/{key_id}/enable")
async def enable_public_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.enable_public_key(key_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已启用"}


@router.post("/keys/{key_id}/disable")
async def disable_public_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.disable_public_key(key_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已停用"}


@router.post("/keys/{key_id}/revoke")
async def revoke_public_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        await svc.revoke_public_key(key_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已撤销"}


# ── IP 规则 ──


@router.get("/{system_id}/ip-rules", response_model=list[IPRuleResponse])
async def list_ip_rules(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_VIEW)),
):
    svc = CallerSystemService(db)
    try:
        await svc.get_by_system_id(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    rules = await svc.list_ip_rules(system_id)
    return [
        IPRuleResponse(
            id=r.id, rule_id=r.id, system_id=r.system_id,
            ip_cidr=r.ip_cidr, description=r.description, status=r.status,
            row_version=r.row_version,
            created_at=r.create_time,
        )
        for r in rules
    ]


@router.post("/{system_id}/ip-rules", response_model=IPRuleResponse, status_code=201)
async def add_ip_rule(
    system_id: str,
    body: AddIPRuleRequest,
    db: AsyncSession = Depends(get_db),
    account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    # 通配 IP 规则属于高风险配置，需要额外的 caller_system:allow_any_ip 操作项
    if body.ip_cidr.strip() == "*":
        from toolhive.services.role_service import RoleService
        role_svc = RoleService(db)
        if not await role_svc.check_operation(
            account.id, OperationCode.CALLER_SYSTEM_ALLOW_ANY_IP
        ):
            raise HTTPException(
                status_code=403,
                detail="缺少操作项: caller_system:allow_any_ip",
            )
    svc = CallerSystemService(db)
    try:
        rule = await svc.add_ip_rule(
            system_id=system_id,
            ip_cidr=body.ip_cidr,
            description=body.description,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IPRuleResponse(
        id=rule.id, rule_id=rule.id, system_id=rule.system_id,
        ip_cidr=rule.ip_cidr, description=rule.description, status=rule.status,
        row_version=rule.row_version,
        created_at=rule.create_time,
    )


@router.patch("/ip-rules/{rule_id}/status")
async def update_ip_rule_status(
    rule_id: str,
    body: StatusRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_MANAGE)),
):
    svc = CallerSystemService(db)
    try:
        status = (
            IPRuleStatus.DISABLED if body.reason else IPRuleStatus.ACTIVE
        )
        await svc.update_ip_rule_status(rule_id, status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "操作成功"}


# ── 运行策略与工具范围 ──


@router.get("/{system_id}/runtime-policy", response_model=RuntimePolicyResponse)
async def get_runtime_policy(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """查询调用系统运行策略；未配置时返回 404。"""
    svc = CallerSystemService(db)
    try:
        policy = await svc.get_runtime_policy(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if policy is None:
        raise HTTPException(status_code=404, detail="运行策略未配置")
    return RuntimePolicyResponse(
        system_id=policy.system_id,
        allowed_api_patterns=policy.get_allowed_api_patterns(),
        qps_limit=policy.qps_limit,
        concurrency_limit=policy.concurrency_limit,
        quota_per_day=policy.quota_per_day,
        request_timeout_seconds=policy.request_timeout_seconds,
        circuit_breaker_enabled=policy.circuit_breaker_enabled,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to,
        row_version=policy.row_version,
        created_at=policy.create_time,
        updated_at=policy.update_time,
    )


@router.put("/{system_id}/runtime-policy", response_model=RuntimePolicyResponse)
async def save_runtime_policy(
    system_id: str,
    body: RuntimePolicyRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """保存调用系统运行策略（整存，API 范围非空）。"""
    svc = CallerSystemService(db)
    try:
        policy = await svc.save_runtime_policy(
            system_id=system_id,
            allowed_api_patterns=body.allowed_api_patterns,
            qps_limit=body.qps_limit,
            concurrency_limit=body.concurrency_limit,
            quota_per_day=body.quota_per_day,
            request_timeout_seconds=body.request_timeout_seconds,
            circuit_breaker_enabled=body.circuit_breaker_enabled,
            effective_from=body.effective_from,
            effective_to=body.effective_to,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RuntimePolicyResponse(
        system_id=policy.system_id,
        allowed_api_patterns=policy.get_allowed_api_patterns(),
        qps_limit=policy.qps_limit,
        concurrency_limit=policy.concurrency_limit,
        quota_per_day=policy.quota_per_day,
        request_timeout_seconds=policy.request_timeout_seconds,
        circuit_breaker_enabled=policy.circuit_breaker_enabled,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to,
        row_version=policy.row_version,
        created_at=policy.create_time,
        updated_at=policy.update_time,
    )


@router.get("/{system_id}/tool-scopes", response_model=list[ToolScopeResponse])
async def list_tool_scopes(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """查询调用系统的工具/能力包范围。"""
    svc = CallerSystemService(db)
    try:
        scopes = await svc.list_tool_scopes(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [
        ToolScopeResponse(
            id=s.id,
            system_id=s.system_id,
            scope_type=s.scope_type,
            scope_code=s.scope_code,
            status=s.status,
            row_version=s.row_version,
            created_at=s.create_time,
        )
        for s in scopes
    ]


@router.put("/{system_id}/tool-scopes", response_model=list[ToolScopeResponse])
async def replace_tool_scopes(
    system_id: str,
    body: ReplaceToolScopesRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """全量替换调用系统的工具/能力包范围。"""
    svc = CallerSystemService(db)
    try:
        scopes = await svc.replace_tool_scopes(
            system_id=system_id,
            items=[item.model_dump() for item in body.items],
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [
        ToolScopeResponse(
            id=s.id,
            system_id=s.system_id,
            scope_type=s.scope_type,
            scope_code=s.scope_code,
            status=s.status,
            row_version=s.row_version,
            created_at=s.create_time,
        )
        for s in scopes
    ]


# ── 紧急禁用 ──


@router.post("/{system_id}/emergency-disable")
async def emergency_disable(
    system_id: str,
    body: EmergencyDisableRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """系统级紧急禁用（仅对已启用系统生效）。"""
    svc = CallerSystemService(db)
    try:
        await svc.emergency_disable(system_id, body.reason)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已紧急禁用"}


@router.post("/{system_id}/emergency-enable")
async def emergency_enable(
    system_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CALLER_SYSTEM_POLICY)),
):
    """解除系统级紧急禁用。"""
    svc = CallerSystemService(db)
    try:
        await svc.emergency_enable(system_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已解除紧急禁用"}
