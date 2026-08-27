"""Catalog 管理 API schemas。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime

# ── Provider ──


class ProviderTargetSecurityConfig(BaseModel):
    """http 类型 Provider 的目标安全配置。"""

    allowed_domains: list[str] = Field(min_length=1)
    allowed_ports: list[int] = Field(default_factory=list)
    path_prefix: str | None = None
    protocols: list[str] = Field(default_factory=lambda: ["https"])
    dns_tls_verification: bool = True
    allowed_cidrs: list[str] = Field(default_factory=list)


class CreateProviderRequest(BaseModel):
    provider_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    provider_type: str = Field(default="http", pattern="^(builtin|http)$")
    description: str | None = None
    target_security_config: ProviderTargetSecurityConfig | None = None


class UpdateProviderRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    target_security_config: ProviderTargetSecurityConfig | None = None
    row_version: int | None = Field(None, ge=0)


class ProviderResponse(BaseModel):
    id: str
    provider_code: str
    name: str
    provider_type: str
    status: str
    description: str | None
    target_security_config: dict[str, Any] | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class ProviderListResponse(BaseModel):
    items: list[ProviderResponse]
    total: int


# ── 能力包 ──


class CreateCapabilityPackRequest(BaseModel):
    pack_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None


class UpdateCapabilityPackRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    row_version: int | None = Field(None, ge=0)


class CapabilityPackResponse(BaseModel):
    id: str
    pack_code: str
    name: str
    description: str | None
    status: str
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class CapabilityPackListResponse(BaseModel):
    items: list[CapabilityPackResponse]
    total: int


class ReplaceToolsRequest(BaseModel):
    tool_ids: list[str] = Field(default_factory=list)


class ReplaceSystemsRequest(BaseModel):
    system_ids: list[str] = Field(default_factory=list)


# ── 工具 ──


class CreateToolRequest(BaseModel):
    namespace: str = Field(min_length=1, max_length=128)
    tool_code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    risk_level: str = Field(default="low", pattern="^(low|medium|high)$")
    discoverable: bool = True
    executable: bool = True
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None


class UpdateToolRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    risk_level: str | None = Field(None, pattern="^(low|medium|high)$")
    discoverable: bool | None = None
    executable: bool | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    row_version: int | None = Field(None, ge=0)


class ToolResponse(BaseModel):
    id: str
    namespace: str
    tool_code: str
    full_code: str
    name: str
    description: str | None
    risk_level: str
    discoverable: bool
    executable: bool
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    status: str
    default_version_id: str | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class ToolListResponse(BaseModel):
    items: list[ToolResponse]
    total: int


# ── 工具版本与执行绑定 ──


class ExecutionBindingRequest(BaseModel):
    """执行绑定写入对象（挂在工具版本下）。"""

    provider_id: str
    method: str = Field(default="COMPUTE", max_length=16)
    path_template: str = Field(min_length=1, max_length=512)
    parameter_mapping: dict[str, Any] | None = None
    allowed_headers: list[str] | None = None
    response_handling: dict[str, Any] | None = None
    timeout_seconds: int | None = Field(None, ge=1, le=300)
    retry_max: int | None = Field(None, ge=0, le=10)
    idempotent: bool = True


class CreateVersionRequest(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    release_note: str | None = None
    binding: ExecutionBindingRequest | None = None


class UpdateVersionRequest(BaseModel):
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    release_note: str | None = None
    binding: ExecutionBindingRequest | None = None
    clear_binding: bool = False
    row_version: int | None = Field(None, ge=0)


class ExecutionBindingResponse(BaseModel):
    id: str
    version_id: str
    provider_id: str
    provider_code: str
    provider_name: str
    method: str
    path_template: str
    parameter_mapping: dict[str, Any] | None
    allowed_headers: list[str] | None
    response_handling: dict[str, Any] | None
    timeout_seconds: int | None
    retry_max: int | None
    idempotent: bool
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class ToolVersionResponse(BaseModel):
    id: str
    tool_id: str
    version: str
    status: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    release_note: str | None
    review_comment: str | None
    row_version: int
    is_default: bool = False
    created_at: UTCDateTime
    updated_at: UTCDateTime | None
    binding: ExecutionBindingResponse | None = None


class ToolDetailResponse(ToolResponse):
    versions: list[ToolVersionResponse] = Field(default_factory=list)


class PublishVersionRequest(BaseModel):
    set_default: bool = False
    comment: str | None = Field(None, max_length=512)


class ReviewRequest(BaseModel):
    comment: str | None = Field(None, max_length=512)


class StatusCommentRequest(BaseModel):
    comment: str | None = Field(None, max_length=512)


# ── 审核与历史 ──


class PendingReviewItemResponse(BaseModel):
    version_id: str
    tool_id: str
    tool_name: str
    full_code: str
    version: str
    release_note: str | None
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    submitter_account_id: str | None
    created_at: UTCDateTime


class PendingReviewListResponse(BaseModel):
    items: list[PendingReviewItemResponse]
    total: int


class HistoryItemResponse(BaseModel):
    kind: str
    id: str
    version_id: str
    action: str
    comment: str | None
    operator_account_id: str | None
    from_status: str | None = None
    to_status: str | None = None
    created_at: UTCDateTime
