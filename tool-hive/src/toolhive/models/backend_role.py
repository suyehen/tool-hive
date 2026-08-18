"""后台角色 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import RoleStatus
from toolhive.models.base import Base, AuditMixin, UUIDPrimaryKeyMixin


class BackendRole(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """后台角色。"""

    __tablename__ = "backend_role"

    name: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
    )
    description: Mapped[str | None] = mapped_column(
        String(512), nullable=True,
    )
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RoleStatus.ACTIVE, index=True,
    )  # active | disabled | archived

    def is_active(self) -> bool:
        return self.status == RoleStatus.ACTIVE
