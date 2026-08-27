"""运行侧高风险执行确认 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, UUIDPrimaryKeyMixin


class RuntimeConfirmation(Base, UUIDPrimaryKeyMixin):
    """高风险工具执行确认申请（令牌只存 SHA-256 哈希）。"""

    __tablename__ = "runtime_confirmation"

    system_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    tool_id: Mapped[str] = mapped_column(String(32), nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tool_code: Mapped[str] = mapped_column(String(256), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True,
    )  # pending | consumed | expired
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
