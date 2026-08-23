"""ORM 基类。提供通用字段和 mixin。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from toolhive.core.snowflake import generate_id


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""
    pass


def gen_id() -> str:
    """生成业务主键雪花 ID（十进制字符串）。"""
    return generate_id()


class UUIDPrimaryKeyMixin:
    """UUID 主键 mixin。"""

    id: Mapped[str] = mapped_column(
        primary_key=True,
        default=gen_id,
        index=True,
    )


class AuditMixin:
    """统一审计字段 mixin：时间与操作人 ID（与 init.sql 保持一致）。"""

    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
    create_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
