"""管理操作审计 ORM 模型（追加式、不可修改）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, UUIDPrimaryKeyMixin


class ManagementAuditLog(Base, UUIDPrimaryKeyMixin):
    """管理操作审计记录。

    追加式写入，不更新、不删除；成功审计与业务变更同事务提交，
    失败审计通过独立事务立即提交。
    """

    __tablename__ = "management_audit_log"

    actor_account_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True,
    )
    actor_account_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )
    actor_system_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )
    object_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    object_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    before_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success",
    )  # success | failure
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
