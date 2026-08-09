"""Capability / EntitlementBundle / PolicyBinding 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Capability(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "capability"

    capability_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EntitlementBundle(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "entitlement_bundle"

    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_bundle_id: Mapped[str | None] = mapped_column(ForeignKey("entitlement_bundle.id"))
    capabilities: Mapped[str | None] = mapped_column(Text)  # JSON array of capability_ids


class PolicyBinding(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "policy_binding"

    role_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_id: Mapped[str] = mapped_column(ForeignKey("entitlement_bundle.id"), nullable=False)
    tool_id: Mapped[str | None] = mapped_column(ForeignKey("tool.tool_id"))  # null = all tools
    risk_threshold: Mapped[str] = mapped_column(String(32), default="medium")
    extra_rules: Mapped[str | None] = mapped_column(Text)  # JSON 附加规则
