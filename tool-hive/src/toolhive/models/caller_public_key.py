"""调用系统公钥 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import PublicKeyStatus
from toolhive.models.base import Base, AuditMixin, UUIDPrimaryKeyMixin


class CallerPublicKey(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """调用系统公钥记录。"""

    __tablename__ = "caller_public_key"

    key_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
    )
    system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("caller_system.system_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_key: Mapped[str] = mapped_column(
        Text, nullable=False,
    )  # PEM SubjectPublicKeyInfo
    fingerprint: Mapped[str] = mapped_column(
        String(128), nullable=False,
    )  # SHA-256
    algorithm: Mapped[str] = mapped_column(
        String(32), nullable=False, default="RSA-PSS-SHA256",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PublicKeyStatus.PENDING, index=True,
    )  # pending | active | disabled | expired | revoked
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )

    def is_valid(self) -> bool:
        if self.status not in (
            PublicKeyStatus.PENDING,
            PublicKeyStatus.ACTIVE,
        ):
            return False
        now = datetime.utcnow()
        if self.effective_from > now:
            return False
        if self.effective_to and self.effective_to <= now:
            return False
        return True
