"""TOTP 测试。"""

from __future__ import annotations

import hashlib
import time
from unittest.mock import patch

import pytest

from toolhive.services.security.totp import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    generate_recovery_codes,
    generate_totp_secret,
    generate_totp_uri,
    verify_totp,
)


class TestTOTPGeneration:
    """TOTP 密钥与 URI 生成。"""

    def test_generate_secret_length(self) -> None:
        secret = generate_totp_secret()
        assert len(secret) >= 16  # Base32 编码至少 16 字符

    def test_generate_secret_unique(self) -> None:
        secrets = {generate_totp_secret() for _ in range(10)}
        assert len(secrets) == 10

    def test_generate_uri_format(self) -> None:
        secret = generate_totp_secret()
        uri = generate_totp_uri(secret, "admin")
        assert uri.startswith("otpauth://totp/")
        assert "ToolHive" in uri
        assert "admin" in uri
        assert secret in uri
        assert "SHA1" in uri
        assert "digits=6" in uri

    def test_uri_url_encodes_spaces(self) -> None:
        secret = generate_totp_secret()
        uri = generate_totp_uri(secret, "admin user")
        assert "%20" in uri


class TestTOTPVerify:
    """TOTP 校验。"""

    def test_verify_correct_code(self) -> None:
        secret = generate_totp_secret()
        # 用当前时间窗口计算期望值
        import base64
        import hmac
        import struct

        decoded = base64.b32decode(secret.upper())
        counter = int(time.time()) // 30
        msg = counter.to_bytes(8, byteorder="big")
        mac = hmac.digest(decoded, msg, hashlib.sha1)
        offset = mac[-1] & 0x0F
        binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
        expected = str(binary % (10 ** 6)).zfill(6)

        assert verify_totp(secret, expected) is True

    def test_reject_short_code(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "12345") is False

    def test_reject_non_digit(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "abc123") is False

    def test_reject_wrong_code(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "999999") is False


class TestRecoveryCodes:
    """恢复码测试。"""

    def test_generate_count(self) -> None:
        rc = generate_recovery_codes()
        assert len(rc.plain_codes) == 8
        assert len(rc.hash_codes) == 8

    def test_hash_matches_plain(self) -> None:
        rc = generate_recovery_codes()
        for plain, expected_hash in zip(rc.plain_codes, rc.hash_codes):
            computed = hashlib.sha256(plain.encode()).hexdigest()
            assert computed == expected_hash

    def test_codes_are_unique(self) -> None:
        rc = generate_recovery_codes()
        assert len(set(rc.plain_codes)) == 8
        assert len(set(rc.hash_codes)) == 8


class TestTOTPEncryption:
    """TOTP 密钥加密/解密。"""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        secret = generate_totp_secret()
        encrypted = encrypt_totp_secret(secret)
        assert encrypted != secret
        decrypted = decrypt_totp_secret(encrypted)
        assert decrypted == secret
