"""调用系统运行策略 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CallerRuntimePolicy(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """调用系统运行策略：运行 API 范围、流量参数与有效期（每系统一条）。"""

    __tablename__ = "caller_runtime_policy"

    system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("caller_system.system_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    allowed_api_patterns: Mapped[str] = mapped_column(
        Text, nullable=False,
    )  # JSON 数组：允许访问的运行 API 端点标识
    qps_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    quota_per_day: Mapped[int] = mapped_column(Integer, nullable=False)
    request_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    circuit_breaker_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    def get_allowed_api_patterns(self) -> list[str]:
        """解析允许的运行 API 范围列表。"""
        import json
        return json.loads(self.allowed_api_patterns)
