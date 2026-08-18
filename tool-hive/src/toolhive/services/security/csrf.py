"""CSRF Token 生成与校验。"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from toolhive.config import AdminSecuritySettings

_admin_security = AdminSecuritySettings()


def configure_security(admin_security: AdminSecuritySettings) -> None:
    """启动阶段绑定管理安全配置分区。"""
    global _admin_security
    _admin_security = admin_security


def _get_csrf_secret() -> str:
    """获取 CSRF 签名密钥。"""
    secret = _admin_security.csrf_secret
    if not secret:
        # 开发环境默认 key（生产必须配置）
        secret = "TOOLHIVE_CSRF_DEV_KEY_CHANGE_IN_PRODUCTION"
    return secret


def generate_csrf_token(session_id: str) -> str:
    """基于 session_id 生成 CSRF Token（HMAC-SHA256）。"""
    raw = f"{session_id}:{secrets.token_hex(16)}"
    mac = hmac.digest(
        _get_csrf_secret().encode(),
        raw.encode(),
        hashlib.sha256,
    )
    signature = mac.hex()
    return f"{raw}:{signature}"


def verify_csrf_token(session_id: str, token: str) -> bool:
    """校验 CSRF Token。"""
    try:
        parts = token.rsplit(":", 1)
        if len(parts) != 2:
            return False
        raw, provided_sig = parts
        expected_sig = hmac.digest(
            _get_csrf_secret().encode(),
            raw.encode(),
            hashlib.sha256,
        ).hex()
        if not hmac.compare_digest(provided_sig, expected_sig):
            return False
        # 校验 session_id 匹配
        token_session_id = raw.split(":", 1)[0]
        return token_session_id == session_id
    except Exception:
        return False
