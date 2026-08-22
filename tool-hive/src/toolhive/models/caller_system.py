"""调用系统 ORM 模型。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import CallerSystemStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CallerSystem(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """调用系统：调用 ToolHive 运行接口的外部软件系统。"""

    __tablename__ = "caller_system"

    system_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    environment: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
    )  # development | production
    department: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CallerSystemStatus.DRAFT, index=True,
    )  # draft | enabled | disabled | revoked
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    deactivated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    emergency_disabled_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    emergency_disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    def is_enabled(self) -> bool:
        if self.status != CallerSystemStatus.ENABLED:
            return False
        return self.effective_state == "effective"

    @property
    def effective_state(self) -> str:
        """有效期实时计算结果（不依赖生命周期状态）。

        - ``not_started``：未到 effective_from，尚未生效；
        - ``effective``：处于有效期内（或未配置有效期）；
        - ``expired``：已超过 effective_to。
        """
        now = datetime.now(UTC)
        if self.effective_from and self.effective_from > now:
            return "not_started"
        if self.effective_to and self.effective_to <= now:
            return "expired"
        return "effective"
