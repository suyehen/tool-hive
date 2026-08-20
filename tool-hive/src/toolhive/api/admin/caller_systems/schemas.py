"""调用系统 API schemas。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class CreateCallerSystemRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    environment: str = Field(default="production", pattern="^(development|production)$")
    description: str | None = Field(None)
    department: str | None = Field(None, max_length=256)
    owner: str | None = Field(None, max_length=256)
    contact: str | None = Field(None, max_length=256)
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class UpdateCallerSystemRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    department: str | None = None
    owner: str | None = None
    contact: str | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    row_version: int | None = Field(None, ge=0, description="乐观锁版本号，可选")


class StatusRequest(BaseModel):
    reason: str | None = Field(None, description="停用/注销原因")


class CallerSystemResponse(BaseModel):
    id: str
    system_id: str
    name: str
    description: str | None
    environment: str
    department: str | None
    owner: str | None
    contact: str | None
    status: str
    effective_from: UTCDateTime | None
    effective_to: UTCDateTime | None
    deactivated_reason: str | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class CallerSystemListResponse(BaseModel):
    items: list[CallerSystemResponse]
    total: int


# ── 公钥 ──

class AddPublicKeyRequest(BaseModel):
    public_key: str = Field(min_length=1, description="PEM SubjectPublicKeyInfo 格式")
    algorithm: str = Field(default="RSA-PSS-SHA256")
    effective_to: datetime | None = None


class PublicKeyResponse(BaseModel):
    id: str
    key_id: str
    system_id: str
    fingerprint: str
    algorithm: str
    status: str
    effective_from: UTCDateTime
    effective_to: UTCDateTime | None
    row_version: int
    created_at: UTCDateTime


# ── IP 规则 ──

class AddIPRuleRequest(BaseModel):
    ip_cidr: str = Field(min_length=1, max_length=64, description="IP / CIDR / *")
    description: str | None = None


class IPRuleResponse(BaseModel):
    id: str
    rule_id: str | None  # deprecated alias
    system_id: str
    ip_cidr: str
    description: str | None
    status: str
    row_version: int
    created_at: UTCDateTime


# ── 运行策略 ──

class RuntimePolicyRequest(BaseModel):
    allowed_api_patterns: list[str] = Field(
        min_length=1,
        description="允许访问的运行 API 端点标识列表，如 /api/runtime/v1/tools/execute",
    )
    qps_limit: int = Field(ge=1, description="每秒请求上限")
    concurrency_limit: int = Field(ge=1, description="并发请求上限")
    quota_per_day: int = Field(ge=1, description="每日配额上限")
    request_timeout_seconds: int = Field(ge=1, le=300, description="请求超时（秒）")
    circuit_breaker_enabled: bool = Field(
        default=True, description="是否启用熔断",
    )
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    row_version: int | None = Field(None, ge=0, description="乐观锁版本号，可选")


class RuntimePolicyResponse(BaseModel):
    system_id: str
    allowed_api_patterns: list[str]
    qps_limit: int
    concurrency_limit: int
    quota_per_day: int
    request_timeout_seconds: int
    circuit_breaker_enabled: bool
    effective_from: UTCDateTime | None
    effective_to: UTCDateTime | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


# ── 工具范围 ──

class ToolScopeItemRequest(BaseModel):
    scope_type: str = Field(
        default="tool", pattern="^(capability|tool)$",
        description="范围类型：capability（能力包）| tool（工具）",
    )
    scope_code: str = Field(min_length=1, max_length=256)
    status: str = Field(
        default="active", pattern="^(active|disabled)$",
        description="工具级禁用通过 disabled 表达",
    )


class ReplaceToolScopesRequest(BaseModel):
    items: list[ToolScopeItemRequest] = Field(default_factory=list)


class ToolScopeResponse(BaseModel):
    id: str
    system_id: str
    scope_type: str
    scope_code: str
    status: str
    row_version: int
    created_at: UTCDateTime


# ── 紧急禁用 ──

class EmergencyDisableRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
