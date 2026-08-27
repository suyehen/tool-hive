"""运行侧基础 Trace ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, UUIDPrimaryKeyMixin


class RuntimeTraceLog(Base, UUIDPrimaryKeyMixin):
    """运行请求 Trace 记录：认证、授权、流量决策与请求完成事件。"""

    __tablename__ = "runtime_trace_log"

    trace_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    system_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success",
    )  # success | failure
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
