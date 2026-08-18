"""TOTP 生成与校验（RFC 6238）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import NamedTuple

from cryptography.fernet import Fernet

from toolhive.config import AdminSecuritySettings
from toolhive.core.constants import (
    TOTP_ISSUER,
    TOTP_RECOVERY_CODE_BYTES,
    TOTP_RECOVERY_CODE_COUNT,
)

# ── TOTP 参数 ──
_TOTP_DIGITS: int = 6
_TOTP_PERIOD: int = 30
_TOTP_TOLERANCE_WINDOWS: int = 1  # 前后各 1 个窗口

_admin_security = AdminSecuritySettings()


def configure_security(admin_security: AdminSecuritySettings) -> None:
    """启动阶段绑定管理安全配置分区。"""
    global _admin_security
    _admin_security = admin_security


class RecoveryCodes(NamedTuple):
    """恢复码生成结果。"""
    plain_codes: list[str]    # 明文，仅展示一次
    hash_codes: list[str]     # SHA-256 哈希，持久化存储


def generate_totp_secret() -> str:
    """生成符合 RFC 6238 的 Base32 TOTP 密钥（20 字节）。"""
    raw = os.urandom(20)
    return base64.b32encode(raw).decode("ascii")


def generate_totp_uri(secret: str, username: str, issuer: str = TOTP_ISSUER) -> str:
    """生成 otpauth:// URI，供前端生成 QR 码。"""
    encoded_issuer = _url_encode(issuer)
    return f"otpauth://totp/{encoded_issuer}:{_url_encode(username)}?secret={secret}&issuer={encoded_issuer}&algorithm=SHA1&digits={_TOTP_DIGITS}&period={_TOTP_PERIOD}"


def generate_recovery_codes(count: int = TOTP_RECOVERY_CODE_COUNT) -> RecoveryCodes:
    """生成一次性恢复码（明文 + SHA-256 哈希）。"""
    plain = [
        secrets.token_hex(TOTP_RECOVERY_CODE_BYTES)
        for _ in range(count)
    ]
    hashed = [
        hashlib.sha256(c.encode()).hexdigest()
        for c in plain
    ]
    return RecoveryCodes(plain_codes=plain, hash_codes=hashed)


def verify_totp(secret: str, code: str) -> bool:
    """校验 TOTP 动态码。支持前后各 1 个时间窗口。"""
    if not code.isdigit() or len(code) != _TOTP_DIGITS:
        return False

    current_window = int(time.time()) // _TOTP_PERIOD
    decoded_secret = base64.b32decode(secret.upper())

    for offset in range(-_TOTP_TOLERANCE_WINDOWS, _TOTP_TOLERANCE_WINDOWS + 1):
        if _compute_totp(decoded_secret, current_window + offset) == code:
            return True
    return False


def _compute_totp(secret_bytes: bytes, counter: int) -> str:
    """计算 TOTP 值。"""
    msg = counter.to_bytes(8, byteorder="big")
    mac = hmac.digest(secret_bytes, msg, hashlib.sha1)
    offset = mac[-1] & 0x0F
    binary = int.from_bytes(mac[offset:offset + 4], byteorder="big") & 0x7FFFFFFF
    return str(binary % (10 ** _TOTP_DIGITS)).zfill(_TOTP_DIGITS)


def _url_encode(s: str) -> str:
    """简单 URL 编码（用于 otpauth URI）。"""
    return s.replace(" ", "%20")


# ── TOTP 密钥加密（使用 Fernet / AES-CBC） ──

def _get_fernet() -> Fernet:
    """从配置获取或派生出 Fernet 实例。"""
    key = _admin_security.totp_encryption_key
    if not key:
        # 开发环境：派生一个不安全的 key；生产环境必须配置
        key = base64.urlsafe_b64encode(hashlib.sha256(b"TOOLHIVE_TOTP_DEFAULT").digest()).decode()
    else:
        # 确保 key 是有效的 Fernet key（32 字节 base64url）
        key_bytes = key.encode("utf-8")
        if len(key_bytes) != 44:
            key = base64.urlsafe_b64encode(
                hashlib.sha256(key_bytes).digest()
            ).decode()
    return Fernet(key.encode() if len(key) == 44 else key)


def encrypt_totp_secret(secret: str) -> str:
    """加密 TOTP 密钥。"""
    f = _get_fernet()
    return f.encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    """解密 TOTP 密钥。"""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()
