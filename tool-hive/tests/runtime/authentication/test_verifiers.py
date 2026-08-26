"""验签器注册表与各签名算法验证测试（含固定测试向量）。"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from toolhive.core.enums import SigningAlgorithm
from toolhive.core.exceptions import ValidationError
from toolhive.runtime.authentication.verifiers import (
    VERIFIERS,
    Ed25519Verifier,
    RsaPssSha256Verifier,
    get_verifier,
)

CANONICAL = (
    b"POST\n/api/runtime/v1/tools/execute\n2026-08-26T00:00:00Z\n"
    b"nonce-9f86d081884c7d65\n"
    b"sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"
)

RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtzeANQWsGjpgo0y3qPZ+
LTR0HG2jJKYu6/HevqQn8Nybo7l1qT73f89pClaswTXuL350AxvemWaGSVleXJRl
72iWkbFyxYUUYGXM+ZhRBDpd7o1mlHL8QxnczhxrWeaqzQv/eMaBvspCQdlQDzz+
U0yzTaSCxlU/dZagZNTlSMu+hNUEzFhCvdgYdiCSjfwjjD/1bwtieTHMfq97yavj
PWSlGOq84rtPMdZ5ldJ3x3t50b9smrkVQAOsiy3tnVW5H4SYvs56/281LoOkSqMV
Lm3fKO3Yn3PEHKA538wjfSweFPurK5zL985mSI7/59crjwpscRRXwntmLZWRREj6
3wIDAQAB
-----END PUBLIC KEY-----
"""

RSA_SIGNATURE = base64.b64decode(
    "GXgOb+UnED6BBmIdoQTrMaADrWzJCYs8V9QDZdUDEkC3kBl+68kfhwRIOE+QSUS7"
    "NikOp0iySZztYJEzW/A6pIYviil2wFvympWZ8goq1Emf4VHZbmxLl8PMoDU8LBMT"
    "NSzn/h5s3Nq2fH/379q5dDxyN2IjfiZnor8QFbW6D1S3XToR5/P7rPhlp8geoo1c"
    "GecO/F4yOejsFeAZLiZNUJh1YGrVvqUUR3yw4PJoiRYnoESaZwpNPykLCJuXLrbH"
    "jdQxvf4XQYNfwfFGHWhtg22OGKl2lsLkWU9Pr7L5cYCD5/l45OYeteRqoUQswqDY9"
    "BbRtmvZCMccP4z9kDNiHQ=="
)

ED25519_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEANPk0R7sNENusK5UQz03QONuE85omwdjiNxxJLi8A2hA=
-----END PUBLIC KEY-----
"""

ED25519_SIGNATURE = base64.b64decode(
    "iF2M2ALT82GP7qUVLi3nc7/Cz2sd39ET3DGA+dKwlx1O1JPVyEK3XG2rwOMtCfXn"
    "1RovE1TQgfTR2QDUFCbeCw=="
)


def _generate_rsa_public_key_pem(key_size: int = 2048) -> str:
    """生成 RSA 公钥 PEM（测试辅助）。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    return key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def _generate_ed25519_public_key_pem() -> str:
    """生成 Ed25519 公钥 PEM（测试辅助）。"""
    key = ed25519.Ed25519PrivateKey.generate()
    return key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def test_rsa_pss_verify_accepts_fixed_vector() -> None:
    """固定 RSA-PSS 测试向量验签通过。"""
    assert RsaPssSha256Verifier().verify(
        CANONICAL, RSA_SIGNATURE, RSA_PUBLIC_KEY_PEM,
    )


def test_rsa_pss_verify_rejects_tampered_canonical() -> None:
    """篡改 canonical 后验签失败。"""
    verifier = RsaPssSha256Verifier()
    tampered = CANONICAL + b"\ntampered"
    assert not verifier.verify(tampered, RSA_SIGNATURE, RSA_PUBLIC_KEY_PEM)


def test_rsa_pss_verify_rejects_wrong_key() -> None:
    """使用错误公钥验签失败。"""
    other_pem = _generate_rsa_public_key_pem()
    assert not RsaPssSha256Verifier().verify(
        CANONICAL, RSA_SIGNATURE, other_pem,
    )


def test_rsa_pss_verify_rejects_invalid_signature_bytes() -> None:
    """随机签名字节验签失败。"""
    assert not RsaPssSha256Verifier().verify(
        CANONICAL, b"\x00" * 256, RSA_PUBLIC_KEY_PEM,
    )


def test_rsa_pss_validate_rejects_malformed_pem() -> None:
    """畸形公钥被拒绝。"""
    with pytest.raises(ValidationError):
        RsaPssSha256Verifier().validate_public_key("not-a-pem")


def test_rsa_pss_validate_rejects_weak_key() -> None:
    """低于阈值的 RSA 公钥被拒绝（默认 2048 位）。"""
    weak_pem = _generate_rsa_public_key_pem(key_size=1024)
    with pytest.raises(ValidationError, match="位长不足"):
        RsaPssSha256Verifier().validate_public_key(weak_pem)


def test_rsa_pss_validate_honors_configured_min_bits() -> None:
    """显式 min_bits 高于密钥位长时拒绝。"""
    with pytest.raises(ValidationError, match="位长不足"):
        RsaPssSha256Verifier().validate_public_key(RSA_PUBLIC_KEY_PEM, min_bits=3072)


def test_rsa_pss_validate_rejects_ed25519_pem() -> None:
    """Ed25519 公钥不能按 RSA 算法入库。"""
    with pytest.raises(ValidationError, match="不是 RSA 公钥"):
        RsaPssSha256Verifier().validate_public_key(ED25519_PUBLIC_KEY_PEM)


def test_ed25519_verify_accepts_fixed_vector() -> None:
    """固定 Ed25519 测试向量验签通过。"""
    assert Ed25519Verifier().verify(
        CANONICAL, ED25519_SIGNATURE, ED25519_PUBLIC_KEY_PEM,
    )


def test_ed25519_verify_rejects_tampered_canonical() -> None:
    """篡改 canonical 后 Ed25519 验签失败。"""
    tampered = CANONICAL + b"\ntampered"
    assert not Ed25519Verifier().verify(
        tampered, ED25519_SIGNATURE, ED25519_PUBLIC_KEY_PEM,
    )


def test_ed25519_verify_rejects_wrong_key() -> None:
    """使用错误公钥验签失败。"""
    other_pem = _generate_ed25519_public_key_pem()
    assert not Ed25519Verifier().verify(
        CANONICAL, ED25519_SIGNATURE, other_pem,
    )


def test_ed25519_validate_rejects_malformed_pem() -> None:
    """畸形公钥被拒绝。"""
    with pytest.raises(ValidationError):
        Ed25519Verifier().validate_public_key("not-a-pem")


def test_ed25519_validate_rejects_rsa_pem() -> None:
    """RSA 公钥不能按 Ed25519 算法入库。"""
    with pytest.raises(ValidationError, match="不是 Ed25519 公钥"):
        Ed25519Verifier().validate_public_key(RSA_PUBLIC_KEY_PEM)


def test_get_verifier_returns_registered_verifiers() -> None:
    """注册表按算法标识返回对应验签器。"""
    assert isinstance(
        get_verifier(SigningAlgorithm.RSA_PSS_SHA256), RsaPssSha256Verifier,
    )
    assert isinstance(get_verifier(SigningAlgorithm.ED25519), Ed25519Verifier)


def test_get_verifier_rejects_unknown_algorithm() -> None:
    """未注册算法默认拒绝。"""
    with pytest.raises(ValidationError, match="不支持的签名算法"):
        get_verifier("SM2-SM3")


def test_registry_keys_match_signing_algorithm_enum() -> None:
    """注册表算法与枚举保持一致，防止契约漂移。"""
    assert set(VERIFIERS) == set(SigningAlgorithm)
