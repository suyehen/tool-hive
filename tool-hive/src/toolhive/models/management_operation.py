"""管理操作项 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import OperationStatus
from toolhive.models.base import AuditMixin, Base


class ManagementOperation(Base, AuditMixin):
    """管理操作项。operation_code 为主键，由代码定义。"""

    __tablename__ = "management_operation"

    operation_code: Mapped[str] = mapped_column(
        String(128), primary_key=True,
    )
    category: Mapped[str] = mapped_column(
        String(64), nullable=False, default="other", index=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OperationStatus.ACTIVE,
    )  # active | deprecated

    def is_active(self) -> bool:
        return self.status == OperationStatus.ACTIVE
