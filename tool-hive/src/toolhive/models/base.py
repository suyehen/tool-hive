"""ORM 基类。提供通用字段和 mixin。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""
    pass


def gen_uuid() -> str:
    """生成不带连字符的 UUID 字符串。"""
    return uuid.uuid4().hex


class UUIDPrimaryKeyMixin:
    """UUID 主键 mixin。"""

    id: Mapped[str] = mapped_column(
        primary_key=True,
        default=gen_uuid,
        index=True,
    )


class AuditMixin:
    """统一审计字段 mixin：时间与操作人（与 init.sql 保持一致）。"""

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
    create_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    update_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    create_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    update_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
