"""运行 API 契约 Schema（Resolve / Discover / Execute / Confirmations）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from toolhive.core.time_utils import UTCDateTime


class ToolContextRequest(BaseModel):
    """请求体顶层业务身份上下文（一期声明制）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(None, max_length=128)
    tenant_id: str | None = Field(None, max_length=128)
    role: str | None = Field(None, max_length=128)
    channel: str | None = Field(None, max_length=128)
    session_id: str | None = Field(None, max_length=128)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_code: str | None = Field(None, min_length=1, max_length=256)
    tool_id: str | None = Field(None, min_length=1, max_length=64)
    version: str | None = Field(None, max_length=32)
    context: ToolContextRequest | None = None

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> ResolveRequest:
        """工具完整编码与工具 ID 必须且只能提供一个。"""
        if bool(self.tool_code) == bool(self.tool_id):
            raise ValueError("tool_code 与 tool_id 必须且只能提供一个")
        return self


class ResolveResponse(BaseModel):
    tool_code: str
    name: str
    description: str | None
    risk_level: str
    version: str
    executable: bool
    discoverable: bool = True
    confirmation_required: bool = False
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    trace_id: str


class DiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=20, ge=1, le=50)
    context: ToolContextRequest | None = None


class DiscoverItem(BaseModel):
    tool_code: str
    name: str
    description: str | None
    risk_level: str
    version: str


class DiscoverResponse(BaseModel):
    items: list[DiscoverItem]
    total: int
    limit: int
    degraded: bool = True
    coverage: float = Field(default=1.0, ge=0.0, le=1.0)
    trace_id: str


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arguments: dict[str, Any] = Field(default_factory=dict)
    version: str | None = Field(None, max_length=32)
    idempotency_key: str | None = Field(None, max_length=128)
    context: ToolContextRequest | None = None
    confirmation_id: str | None = Field(None, max_length=64)
    confirmation_token: str | None = Field(None, max_length=256)


class ExecuteResponse(BaseModel):
    tool_code: str
    version: str
    result: dict[str, Any]
    trace_id: str


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_code: str = Field(min_length=1, max_length=256)
    version: str | None = Field(None, max_length=32)


class ConfirmResponse(BaseModel):
    confirmation_id: str
    tool_code: str
    token: str
    expires_at: UTCDateTime
    trace_id: str


class VerifyConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=64)
    token: str = Field(min_length=1, max_length=256)


class VerifyConfirmResponse(BaseModel):
    valid: bool
    tool_code: str
    trace_id: str
