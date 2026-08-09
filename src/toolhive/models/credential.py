"""CredentialRef — 密钥引用，不保存明文。"""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKey


class CredentialRef(Base, TimestampMixin, UUIDPrimaryKey):
    __tablename__ = "credential_ref"

    ref_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(64))
    secret_store_key: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
