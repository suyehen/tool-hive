"""MFA TOTP 配置 ORM 模型。"""

from __future__ import annotations

import json

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MfaConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """管理员 MFA TOTP 配置。"""

    __tablename__ = "mfa_config"

    account_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("management_account.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    encrypted_secret: Mapped[str] = mapped_column(
        String(512), nullable=False,
    )
    recovery_codes_hash: Mapped[str] = mapped_column(
        Text, nullable=False,
    )  # JSON list of SHA-256 hashes
    is_bound: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
    )

    def set_recovery_codes(self, hash_codes: list[str]) -> None:
        """存储恢复码哈希列表（JSON 序列化）。"""
        self.recovery_codes_hash = json.dumps(hash_codes, ensure_ascii=False)

    def get_recovery_codes(self) -> list[str]:
        """解析存储的恢复码哈希列表。"""
        return json.loads(self.recovery_codes_hash)

    def verify_recovery_code(self, plain_code: str) -> bool:
        """校验恢复码并移除已使用的（一次性）。"""
        import hashlib
        code_hash = hashlib.sha256(plain_code.encode()).hexdigest()
        codes = self.get_recovery_codes()
        if code_hash in codes:
            codes.remove(code_hash)
            self.set_recovery_codes(codes)
            return True
        return False
