"""密码历史 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PasswordHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """密码历史记录（用于禁止重复使用最近 N 次密码）。"""

    __tablename__ = "password_history"

    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("management_account.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
