"""Redis 会话管理。支持互斥登录（账号索引双重校验）、超时检查。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import NamedTuple

from toolhive.config import AdminSecuritySettings
from toolhive.core.constants import SESSION_ID_BYTES
from toolhive.infrastructure.redis import get_redis

_admin_security = AdminSecuritySettings()


def configure_security(admin_security: AdminSecuritySettings) -> None:
    """启动阶段绑定管理安全配置分区。"""
    global _admin_security
    _admin_security = admin_security


class SessionData(NamedTuple):
    """会话数据结构。"""
    session_id: str
    account_id: str
    account: str
    security_version: str
    source_ip: str
    created_at: str
    last_activity: str
    expires_at: str


# ── Redis key 前缀 ──
_SESSION_PREFIX: str = "session:"
_ACCOUNT_SESSION_PREFIX: str = "account_session:"


def _session_key(session_id: str) -> str:
    return f"{_SESSION_PREFIX}{session_id}"


def _account_key(account_id: str) -> str:
    return f"{_ACCOUNT_SESSION_PREFIX}{account_id}"


async def create_session(
    account_id: str,
    account: str,
    security_version: int,
    source_ip: str,
) -> str:
    """创建新会话（互斥登录）。

    账号索引 ``account_session:<account_id>`` 是唯一有效会话依据：``SET`` 索引
    为单 key 原子操作，旧会话在读取时通过索引双重校验立即失效；删除旧会话
    key 仅为尽力清理，不承担互斥正确性。
    """
    redis = await get_redis()
    session_id = secrets.token_hex(SESSION_ID_BYTES)

    now = datetime.now(UTC)
    absolute_seconds = _admin_security.session_absolute_timeout_hours * 3600

    expires_at = now.timestamp() + absolute_seconds
    ttl = absolute_seconds

    fields: list[str] = [
        "account_id", account_id,
        "account", account,
        "security_version", str(security_version),
        "source_ip", source_ip,
        "created_at", str(int(now.timestamp())),
        "last_activity", str(int(now.timestamp())),
        "expires_at", str(int(expires_at)),
    ]

    # 尽力清理旧会话 key（并发竞态下可能删不到，正确性由索引双重校验兜底）
    old_session_id = await redis.get(_account_key(account_id))
    if old_session_id:
        await redis.delete(_session_key(old_session_id))

    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_session_key(session_id), mapping=dict(
            zip(fields[::2], fields[1::2])
        ))
        pipe.expire(_session_key(session_id), ttl)
        pipe.set(_account_key(account_id), session_id, ex=ttl)
        await pipe.execute()

    return session_id


async def get_session(session_id: str) -> SessionData | None:
    """读取会话并检查有效性。如果已过期，自动删除。"""
    redis = await get_redis()
    data = await redis.hgetall(_session_key(session_id))
    if not data:
        return None

    account_id = data.get("account_id", "")
    # 互斥登录双重校验：仅账号索引指向的会话有效；被新登录顶掉的旧会话立即失效
    if account_id:
        current = await redis.get(_account_key(account_id))
        if current != session_id:
            await redis.delete(_session_key(session_id))
            return None

    now = datetime.now(UTC)
    last_activity = data.get("last_activity", "0")
    expires_at = data.get("expires_at", "0")

    idle_timeout = _admin_security.session_idle_timeout_minutes * 60

    # 检查空闲超时
    if now.timestamp() - int(last_activity) > idle_timeout:
        await revoke_session(session_id)
        return None

    # 检查绝对超时
    if now.timestamp() > int(expires_at):
        await revoke_session(session_id)
        return None

    # 更新 last_activity
    await redis.hset(
        _session_key(session_id),
        "last_activity",
        str(int(now.timestamp())),
    )
    # 刷新 TTL
    remaining = int(expires_at) - now.timestamp()
    await redis.expire(_session_key(session_id), max(int(remaining), 1))

    return SessionData(
        session_id=session_id,
        account_id=data.get("account_id", ""),
        account=data.get("account", ""),
        security_version=data.get("security_version", "0"),
        source_ip=data.get("source_ip", ""),
        created_at=data.get("created_at", ""),
        last_activity=data.get("last_activity", ""),
        expires_at=data.get("expires_at", ""),
    )


async def revoke_session(session_id: str) -> None:
    """撤销指定会话。

    仅当该会话是账号当前索引指向的会话时才清理索引，避免用旧会话 ID 登出
    误删新登录会话的索引。
    """
    redis = await get_redis()
    data = await redis.hgetall(_session_key(session_id))
    account_id = data.get("account_id")
    if account_id:
        current = await redis.get(_account_key(account_id))
        if current == session_id:
            await redis.delete(_account_key(account_id))
    await redis.delete(_session_key(session_id))


async def revoke_all_sessions(account_id: str) -> None:
    """撤销某账号的全部会话（禁用/重置密码/强制下线）。"""
    redis = await get_redis()
    old_session_id = await redis.get(_account_key(account_id))
    if old_session_id:
        await redis.delete(_session_key(old_session_id))
    await redis.delete(_account_key(account_id))
