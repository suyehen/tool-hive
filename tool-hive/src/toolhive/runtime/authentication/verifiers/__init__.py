"""验签器注册表：按算法分发签名验证实现。

新增算法只需实现 :class:`SignatureVerifier` 并注册到 ``VERIFIERS``；
算法选择必须以 ``key_id`` 查到的公钥记录为准，不得由请求自报。
"""

from __future__ import annotations

from typing import Protocol

from toolhive.core.enums import SigningAlgorithm
from toolhive.core.exceptions import ValidationError

from .ed25519 import Ed25519Verifier
from .rsa_pss import RsaPssSha256Verifier


class SignatureVerifier(Protocol):
    """签名验证器统一接口。"""

    algorithm: str

    def verify(self, canonical: bytes, signature: bytes, public_key_pem: str) -> bool:
        """验证 canonical 内容的签名；签名无效时返回 False。"""
        ...

    def validate_public_key(
        self, public_key_pem: str, min_bits: int | None = None,
    ) -> None:
        """校验公钥格式与强度，非法时抛出 ValidationError。"""
        ...


VERIFIERS: dict[str, SignatureVerifier] = {
    SigningAlgorithm.RSA_PSS_SHA256: RsaPssSha256Verifier(),
    SigningAlgorithm.ED25519: Ed25519Verifier(),
}


def get_verifier(algorithm: str) -> SignatureVerifier:
    """按算法标识获取验签器；未注册的算法默认拒绝。"""
    verifier = VERIFIERS.get(algorithm)
    if verifier is None:
        raise ValidationError(f"不支持的签名算法: {algorithm}")
    return verifier
