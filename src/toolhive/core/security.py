"""管理面认证工具：密码哈希、会话令牌。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext
from toolhive.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(minutes=settings.session_ttl_minutes)
