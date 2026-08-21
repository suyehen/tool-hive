"""调用系统 IP 规则 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import IPRuleStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CallerIPRule(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """调用系统来源 IP 白名单规则。"""

    __tablename__ = "caller_ip_rule"

    system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("caller_system.system_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip_cidr: Mapped[str] = mapped_column(
        String(64), nullable=False,
    )  # 单个 IP、CIDR 或 *
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IPRuleStatus.ACTIVE,
    )  # active | disabled
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
