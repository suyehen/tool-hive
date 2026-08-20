"""管理账号 ORM 模型。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import AccountStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class ManagementAccount(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """管理账号。"""

    __tablename__ = "management_account"

    # ── 身份 ──
    username: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(
        String(256), unique=True, nullable=True, index=True,
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AccountStatus.ENABLED, index=True,
    )  # enabled | disabled | locked

    # ── 登录安全 ──
    login_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # ── 密码管理 ──
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    security_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    def is_enabled(self) -> bool:
        return self.status == AccountStatus.ENABLED

    def is_locked(self) -> bool:
        if self.status == AccountStatus.LOCKED:
            if self.locked_until and self.locked_until > datetime.now(UTC):
                return True
            # 锁定期已过，但状态尚未更新（下一次登录成功时更正）
            if self.locked_until and self.locked_until <= datetime.now(UTC):
                return False
            return True
        return False

    def is_active(self) -> bool:
        """检查账号是否可以正常使用。"""
        return self.status == AccountStatus.ENABLED and not self.is_locked()
