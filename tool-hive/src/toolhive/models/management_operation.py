"""管理操作项 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin


class ManagementOperation(Base, TimestampMixin):
    """管理操作项。operation_code 为主键，由代码定义。"""

    __tablename__ = "management_operation"

    operation_code: Mapped[str] = mapped_column(
        String(128), primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
    )  # active | deprecated

    def is_active(self) -> bool:
        return self.status == "active"
