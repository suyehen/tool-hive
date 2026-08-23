"""管理账号 ORM 模型。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from toolhive.core.enums import AccountStatus
from toolhive.models.account_auth_state import ManagementAccountAuthState
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class ManagementAccount(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """管理账号：身份与生命周期状态（低频数据，认证安全状态见 ManagementAccountAuthState）。"""

    __tablename__ = "management_account"

    # ── 身份 ──
    account: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
    )
    real_name: Mapped[str] = mapped_column(
        String(128), nullable=False,
    )
    external_user_id: Mapped[str | None] = mapped_column(
        String(256), unique=True, nullable=True, index=True,
    )
    email: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
    )
    mobile: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    department: Mapped[str | None] = mapped_column(
        String(256), nullable=True,
    )
    remark: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
    )
    account_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AccountStatus.ENABLED, index=True,
    )  # enabled | disabled | locked | offboarded

    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    # 1:1 认证安全状态（登录失败计数、锁定、密码与临时密码信息）
    auth_state: Mapped[ManagementAccountAuthState | None] = relationship(
        "ManagementAccountAuthState",
        uselist=False,
        lazy="selectin",
    )

    def is_enabled(self) -> bool:
        return self.status == AccountStatus.ENABLED

    def is_locked(self) -> bool:
        if self.status != AccountStatus.LOCKED:
            return False
        # 锁定到期时间在认证状态表中；到期后由下一次登录成功更正状态
        if self.auth_state is None or self.auth_state.locked_until is None:
            return True
        return self.auth_state.locked_until > datetime.now(UTC)

    def is_active(self) -> bool:
        """检查账号是否可以正常使用。"""
        return self.status == AccountStatus.ENABLED and not self.is_locked()
