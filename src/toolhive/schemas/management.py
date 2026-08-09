"""管理面 Schema — 认证、工具管理、Provider、策略。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── 认证 ──
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    token: str
    username: str
    role: str


class UserInfo(BaseModel):
    username: str
    role: str
    enabled: bool


# ── 工具管理 ──
class ToolCreate(BaseModel):
    tool_id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9._-]+$")
    namespace: str = "default"
    name: str = Field(min_length=1, max_length=256)
    description: str | None = None
    risk_level: str = "low"
    tags: list[str] | None = None


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    risk_level: str | None = None
    status: str | None = None
    tags: list[str] | None = None


class ToolVersionBrief(BaseModel):
    version: int
    version_status: str
    changelog: str | None = None


class ToolResponse(BaseModel):
    tool_id: str
    namespace: str
    name: str
    description: str | None
    risk_level: str
    status: str
    tags: list[str] | None
    versions: list[ToolVersionBrief] = []
    created_at: str | None = None


class ToolVersionCreate(BaseModel):
    changelog: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    timeout_ms: int = 30000
    max_retries: int = 0
    idempotent: bool = False


class ToolVersionResponse(BaseModel):
    id: str
    tool_id: str
    version: int
    version_status: str
    changelog: str | None
    description: str | None
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    timeout_ms: int
    max_retries: int
    idempotent: bool
    created_at: str | None


# ── Provider 管理 ──
class ProviderCreate(BaseModel):
    provider_id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=128)
    type: str = "http"
    description: str | None = None
    trust_level: str = "reviewed"
    owner: str | None = None
    config: dict[str, Any] | None = None


class ProviderResponse(BaseModel):
    provider_id: str
    name: str
    type: str
    description: str | None
    trust_level: str
    health_status: str
    enabled: bool
    created_at: str | None


# ── 策略绑定 ──
class PolicyBindingCreate(BaseModel):
    role_id: str = Field(min_length=1, max_length=64)
    bundle_id: str
    tool_id: str | None = None
    risk_threshold: str = "medium"
    extra_rules: dict[str, Any] | None = None


class PolicyBindingResponse(BaseModel):
    id: str
    role_id: str
    bundle_id: str
    tool_id: str | None
    risk_threshold: str
    extra_rules: dict[str, Any] | None
