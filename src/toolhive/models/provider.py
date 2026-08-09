"""Provider 模型 — 描述工具来源和执行适配器。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKey, gen_uuid


class Provider(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "provider"

    provider_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # http, mcp, grpc, local
    description: Mapped[str | None] = mapped_column(Text)
    trust_level: Mapped[str] = mapped_column(String(32), default="reviewed")  # reviewed, internal, external
    owner: Mapped[str | None] = mapped_column(String(128))
    config: Mapped[str | None] = mapped_column(Text)  # JSON 配置引用
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")  # unknown, healthy, unhealthy
    enabled: Mapped[bool] = mapped_column(default=True)
