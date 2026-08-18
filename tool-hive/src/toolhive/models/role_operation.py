"""后台角色与管理操作项的多对多关联表。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, AuditMixin, UUIDPrimaryKeyMixin


class RoleOperation(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """后台角色 ↔ 管理操作项 关联。"""

    __tablename__ = "role_operation"
    __table_args__ = (
        UniqueConstraint("role_id", "operation_code", name="uq_role_operation"),
    )

    role_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("backend_role.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_code: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("management_operation.operation_code", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
