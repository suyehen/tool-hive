"""MCP 接入管理 API schemas。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class UpdateServerConfigRequest(BaseModel):
    server_name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = None
    enabled: bool | None = None
    endpoint_path: str | None = Field(None, min_length=1, max_length=64)
    allowed_hosts: list[str] | None = None
    protocol_versions: list[str] | None = None
    row_version: int | None = Field(None, ge=0)


class ServerConfigResponse(BaseModel):
    id: str
    server_name: str
    description: str | None
    enabled: bool
    endpoint_path: str
    allowed_hosts: list[str]
    protocol_versions: list[str] | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class CreateMcpClientRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None


class UpdateMcpClientRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None
    row_version: int | None = Field(None, ge=0)


class StatusRequest(BaseModel):
    reason: str | None = Field(None, description="停用/注销原因")


class McpClientResponse(BaseModel):
    id: str
    client_code: str
    name: str
    description: str | None
    status: str
    deactivated_reason: str | None
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class McpClientListResponse(BaseModel):
    items: list[McpClientResponse]
    total: int


class IssueTokenResponse(BaseModel):
    token: str = Field(description="访问令牌明文，仅本次返回")
    token_id: str
    client_code: str


class AddIpRuleRequest(BaseModel):
    ip_cidr: str = Field(min_length=1, max_length=64, description="IP / CIDR / *")
    description: str | None = None


class IpRuleStatusUpdateRequest(BaseModel):
    enabled: bool = Field(..., description="目标状态：true 启用 / false 停用")


class IpRuleResponse(BaseModel):
    id: str
    client_id: str
    ip_cidr: str
    description: str | None
    status: str
    row_version: int
    created_at: UTCDateTime


class ScopeItemRequest(BaseModel):
    scope_type: str = Field(
        default="tool", pattern="^(capability|namespace|tool)$",
    )
    scope_code: str = Field(min_length=1, max_length=256)
    status: str = Field(default="active", pattern="^(active|disabled)$")


class ReplaceScopesRequest(BaseModel):
    items: list[ScopeItemRequest] = Field(default_factory=list)


class ScopeResponse(BaseModel):
    id: str
    client_id: str
    scope_type: str
    scope_code: str
    status: str
    row_version: int
    created_at: UTCDateTime
    reference_exists: bool = True
    reference_archived: bool = False


class ExposedToolResponse(BaseModel):
    id: str
    full_code: str
    name: str
    risk_level: str
    status: str
    mcp_enabled: bool
    version: str


class TraceEventResponse(BaseModel):
    id: str
    trace_id: str
    action: str
    status: str
    error_code: str | None
    summary: dict | None
    source_ip: str | None
    mcp_client_id: str | None
    occurred_at: UTCDateTime


class CallRecordListResponse(BaseModel):
    items: list[TraceEventResponse]
    total: int


class TraceDetailResponse(BaseModel):
    trace_id: str
    events: list[TraceEventResponse]


class ConsoleDebugRequest(BaseModel):
    tool_code: str = Field(min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConsoleDebugResponse(BaseModel):
    ok: bool
    server_name: str
    discovered: list[str]
    call_text: str
    call_is_error: bool
    trace_id: str | None
    detail: str | None = None
