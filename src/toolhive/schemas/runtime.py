"""运行面 Schema — Resolve 和 Execute。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ── Resolve ──
class ToolContext(BaseModel):
    """调用方身份与上下文，由 CountBot 在服务间认证后传入。"""
    caller_id: str
    account_id: str | None = None
    tenant_id: str | None = None
    role_ids: list[str] = []
    channel: str | None = None
    entry: str | None = None


class ResolveRequest(BaseModel):
    context: ToolContext
    query: str = Field(min_length=1, description="用户自然语言意图")
    intent: str = Field(default="tool_optional", pattern=r"^(direct_answer|tool_optional|tool_required)$")
    target_capabilities: list[str] = []
    max_candidates: int = Field(default=10, ge=1, le=50)
    trace_id: str | None = None


class CandidateTool(BaseModel):
    tool_id: str
    version: int
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    relevance_score: float
    capabilities: list[str] = []


class ResolveResponse(BaseModel):
    candidates: list[CandidateTool]
    coverage: str  # CoverageResult
    retrieval_plan: dict[str, Any] | None = None
    trace_id: str | None = None


# ── Execute ──
class ExecuteRequest(BaseModel):
    context: ToolContext
    tool_id: str
    version: int
    arguments: dict[str, Any]
    confirmation_token: str | None = None
    trace_id: str | None = None


class ExecuteResponse(BaseModel):
    tool_id: str
    version: int
    status: str  # success, error, confirmation_required
    result: Any | None = None
    error: str | None = None
    reason_code: str | None = None
    confirmation_token: str | None = None
    trace_id: str | None = None
    duration_ms: int | None = None
