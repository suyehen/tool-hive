"""RSA-PSS-SHA256 验签器。"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.types import PublicKeyTypes
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from toolhive.core.exceptions import ValidationError

# 协议固定 salt length：与 SHA-256 输出等长，调用方签名必须使用相同长度
PSS_SALT_LENGTH = 32
# RSA 公钥最小位长（未显式配置时的默认值，与 RuntimeSecuritySettings 默认一致）
DEFAULT_RSA_MIN_BITS = 2048


class RsaPssSha256Verifier:
    """RSA-PSS-SHA256 请求签名验证器。"""

    algorithm = "RSA-PSS-SHA256"

    def verify(self, canonical: bytes, signature: bytes, public_key_pem: str) -> bool:
        """验证 RSA-PSS 签名；签名无效时返回 False，不抛异常。"""
        public_key = self._load(public_key_pem)
        try:
            # 按固定 salt length 32 与 MGF1-SHA256 校验 PSS 签名
            public_key.verify(
                signature,
                canonical,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=PSS_SALT_LENGTH,
                ),
                hashes.SHA256(),
            )
        except InvalidSignature:
            return False
        return True

    def validate_public_key(
        self, public_key_pem: str, min_bits: int | None = None,
    ) -> None:
        """校验公钥为可解析的 RSA 公钥且位长不低于阈值。"""
        public_key = self._load(public_key_pem)
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise ValidationError("公钥不是 RSA 公钥")
        threshold = DEFAULT_RSA_MIN_BITS if min_bits is None else min_bits
        if public_key.key_size < threshold:
            raise ValidationError(f"RSA 公钥位长不足，至少需要 {threshold} 位")

    @staticmethod
    def _load(public_key_pem: str) -> PublicKeyTypes:
        """解析 PEM 公钥，格式非法时抛出 ValidationError。"""
        try:
            return load_pem_public_key(public_key_pem.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ValidationError("公钥格式无效或无法解析") from exc
