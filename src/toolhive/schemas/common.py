"""通用 Pydantic Schema。"""

from __future__ import annotations

from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    detail: str
    code: str | None = None


class PaginationParams(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    offset: int
    limit: int


class CoverageResult(str, Enum):
    full_coverage = "full_coverage"
    partial_coverage = "partial_coverage"
    permission_missing = "permission_missing"
    provider_unavailable = "provider_unavailable"
    unsupported = "unsupported"
    uncertain = "uncertain"


class ReasonCode(str, Enum):
    allow = "allow"
    deny = "deny"
    require_confirmation = "require_confirmation"
    async_only = "async_only"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class ToolStatus(str, Enum):
    draft = "draft"
    active = "active"
    deprecated = "deprecated"
    disabled = "disabled"
    archived = "archived"


class VersionStatus(str, Enum):
    draft = "draft"
    active = "active"
    deprecated = "deprecated"
    disabled = "disabled"
    archived = "archived"
