"""Argon2id 密码处理。"""

from __future__ import annotations

import re
import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

from toolhive.config import settings

_ph = PasswordHasher()

# ── 常见弱密码列表（生产环境可扩展） ──
_COMMON_WEAK_PASSWORDS = frozenset({
    "password", "123456", "12345678", "qwerty", "abc123",
    "password123", "admin", "letmein", "welcome", "monkey",
    "dragon", "master", "login", "starwars", "passw0rd",
    "admin123", "qwerty123", "password1", "123456789",
})

# ── 临时密码字符集（排除易混淆字符） ──
_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits
for _c in "0O1lI":
    _TEMP_PASSWORD_ALPHABET = _TEMP_PASSWORD_ALPHABET.replace(_c, "")


def hash_password(password: str) -> str:
    """对明文密码执行 Argon2id 哈希。"""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, bool]:
    """校验密码。

    Returns:
        (is_valid, needs_rehash): 是否匹配，哈希参数是否需要升级。
    """
    try:
        _ph.verify(password_hash, password)
        needs_rehash = _ph.check_needs_rehash(password_hash)
        return True, needs_rehash
    except (VerificationError, InvalidHashError):
        return False, False


def validate_password_strength(
    password: str,
    username: str | None = None,
    external_user_id: str | None = None,
) -> list[str]:
    """校验密码强度，返回违规项列表。"""
    violations: list[str] = []

    if len(password) < settings.password_min_length:
        violations.append(f"密码长度不能少于 {settings.password_min_length} 位")
    if len(password) > settings.password_max_length:
        violations.append(f"密码长度不能超过 {settings.password_max_length} 位")
    if password.lower() in _COMMON_WEAK_PASSWORDS:
        violations.append("密码过于常见")
    if username and username.lower() in password.lower():
        violations.append("密码不能包含用户名")
    if external_user_id and external_user_id.lower() in password.lower():
        violations.append("密码不能包含工号")

    return violations


def generate_temp_password() -> str:
    """生成安全随机的临时密码。"""
    length = max(settings.password_min_length, 16)
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))
