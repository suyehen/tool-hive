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
