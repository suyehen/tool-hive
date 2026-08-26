"""Ed25519 验签器。"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from toolhive.core.exceptions import ValidationError


class Ed25519Verifier:
    """Ed25519 请求签名验证器（公钥长度固定，无强度参数）。"""

    algorithm = "Ed25519"

    def verify(self, canonical: bytes, signature: bytes, public_key_pem: str) -> bool:
        """验证 Ed25519 签名；签名无效时返回 False，不抛异常。"""
        public_key = self._load(public_key_pem)
        try:
            public_key.verify(signature, canonical)
        except InvalidSignature:
            return False
        return True

    def validate_public_key(
        self, public_key_pem: str, min_bits: int | None = None,
    ) -> None:
        """校验公钥为合法的 Ed25519 公钥（忽略 min_bits）。"""
        public_key = self._load(public_key_pem)
        if not isinstance(public_key, ed25519.Ed25519PublicKey):
            raise ValidationError("公钥不是 Ed25519 公钥")

    @staticmethod
    def _load(public_key_pem: str) -> PublicKeyTypes:
        """解析 PEM 公钥，格式非法时抛出 ValidationError。"""
        try:
            return load_pem_public_key(public_key_pem.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValidationError("公钥格式无效或无法解析") from exc
