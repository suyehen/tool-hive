"""调用系统工具范围 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import ToolScopeStatus, ToolScopeType
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CallerToolScope(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """调用系统可访问的工具/能力包范围条目。"""

    __tablename__ = "caller_tool_scope"

    system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("caller_system.system_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ToolScopeType.TOOL,
    )  # capability | tool
    scope_code: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ToolScopeStatus.ACTIVE,
    )  # active | disabled
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
