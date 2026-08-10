"""ORM 基类。提供通用字段和 mixin。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
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


class TimestampMixin:
    """创建/更新时间戳 mixin。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        onupdate=func.now(),
        nullable=True,
    )
