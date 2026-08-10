"""调用系统 API schemas。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    effective_from: str | None
    effective_to: str | None
    deactivated_reason: str | None
    created_at: str
    updated_at: str | None


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
    effective_from: str
    effective_to: str | None
    created_at: str


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
    created_at: str
