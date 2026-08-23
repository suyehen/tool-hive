"""管理账号认证与登录安全状态 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base


class ManagementAccountAuthState(Base, AuditMixin):
    """管理账号认证状态：密码、登录失败计数、锁定与临时密码信息（与 management_account 1:1）。"""

    __tablename__ = "management_account_auth_state"

    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("management_account.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    login_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    security_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
