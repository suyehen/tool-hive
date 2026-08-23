"""管理账号与后台角色的多对多关联表。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class AccountRole(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """管理账号 ↔ 后台角色 关联。"""

    __tablename__ = "management_account_role"
    __table_args__ = (
        UniqueConstraint("account_id", "role_id", name="uq_management_account_role"),
    )

    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("management_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("management_role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
