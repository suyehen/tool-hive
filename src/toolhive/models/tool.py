"""Tool / ToolVersion / ToolBinding 模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKey


class Tool(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "tool"

    tool_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(128), default="default")
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(32), default="low")  # low, medium, high, critical
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft, active, deprecated, disabled, archived
    tags: Mapped[str | None] = mapped_column(Text)  # JSON array


class ToolVersion(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "tool_version"

    tool_id: Mapped[str] = mapped_column(ForeignKey("tool.tool_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    input_schema: Mapped[str | None] = mapped_column(Text)  # JSON Schema
    output_schema: Mapped[str | None] = mapped_column(Text)  # JSON Schema
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)
    max_retries: Mapped[int] = mapped_column(Integer, default=0)
    idempotent: Mapped[bool] = mapped_column(Boolean, default=False)
    version_status: Mapped[str] = mapped_column(String(32), default="draft")
    # draft, active, deprecated, disabled, archived


class ToolBinding(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "tool_binding"

    tool_id: Mapped[str] = mapped_column(ForeignKey("tool.tool_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_id: Mapped[str] = mapped_column(ForeignKey("provider.provider_id"), nullable=False)
    execution_config: Mapped[str | None] = mapped_column(Text)  # JSON, 如 method/path_template/credential_ref
    valid_from: Mapped[str | None] = mapped_column(String(32))
    valid_until: Mapped[str | None] = mapped_column(String(32))
