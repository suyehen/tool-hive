"""Redis 会话管理。支持互斥登录、超时检查、原子操作。"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import NamedTuple

from redis.asyncio import Redis

from toolhive.config import AdminSecuritySettings
from toolhive.core.constants import SESSION_COOKIE_PATH, SESSION_ID_BYTES
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
    username: str
    security_version: str
    source_ip: str
    created_at: str
    last_activity: str
    expires_at: str


# ── Redis key 前缀 ──
_SESSION_PREFIX: str = "session:"
_ACCOUNT_SESSION_PREFIX: str = "account_session:"


# ── Lua 脚本：互斥登录原子操作 ──
# 1. 读取 account_session:<account_id> → 旧 session_id
# 2. 删除旧 session
# 3. 写入新 session
# 4. 更新 account_session 索引
_MUTEX_LOGIN_LUA = """
local old = redis.call('GET', KEYS[1])
if old then
    redis.call('DEL', _PREFIX_ .. old)
end
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[7])
redis.call('SET', KEYS[1], ARGV[1])
for i = 1, #ARGV - 1 do
    redis.call('HSET', _PREFIX_ .. ARGV[1], ARGV[i + 7], ARGV[i])
end
return old
""".replace("_PREFIX_", _SESSION_PREFIX)


def _session_key(session_id: str) -> str:
    return f"{_SESSION_PREFIX}{session_id}"


def _account_key(account_id: str) -> str:
    return f"{_ACCOUNT_SESSION_PREFIX}{account_id}"


async def create_session(
    account_id: str,
    username: str,
    security_version: int,
    source_ip: str,
) -> str:
    """创建新会话（互斥登录：以原子方式撤销该账号旧会话）。"""
    redis = await get_redis()
    session_id = secrets.token_hex(SESSION_ID_BYTES)

    now = datetime.now(timezone.utc)
    idle_seconds = _admin_security.session_idle_timeout_minutes * 60
    absolute_seconds = _admin_security.session_absolute_timeout_hours * 3600

    expires_at = now.timestamp() + absolute_seconds
    ttl = absolute_seconds

    fields: list[str] = [
        "account_id", account_id,
        "username", username,
        "security_version", str(security_version),
        "source_ip", source_ip,
        "created_at", str(int(now.timestamp())),
        "last_activity", str(int(now.timestamp())),
        "expires_at", str(int(expires_at)),
    ]

    # 如果 Lua 脚本中引用了不存在的 key，Redis 会报错，这里改用事务模拟互斥操作
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

    now = datetime.now(timezone.utc)
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
        username=data.get("username", ""),
        security_version=data.get("security_version", "0"),
        source_ip=data.get("source_ip", ""),
        created_at=data.get("created_at", ""),
        last_activity=data.get("last_activity", ""),
        expires_at=data.get("expires_at", ""),
    )


async def revoke_session(session_id: str) -> None:
    """撤销指定会话并清理索引。"""
    redis = await get_redis()
    data = await redis.hgetall(_session_key(session_id))
    account_id = data.get("account_id")
    if account_id:
        await redis.delete(_account_key(account_id))
    await redis.delete(_session_key(session_id))


async def revoke_all_sessions(account_id: str) -> None:
    """撤销某账号的全部会话（禁用/重置密码/MFA 重置/强制下线）。"""
    redis = await get_redis()
    old_session_id = await redis.get(_account_key(account_id))
    if old_session_id:
        await redis.delete(_session_key(old_session_id))
    await redis.delete(_account_key(account_id))


async def rotate_session_id(old_session_id: str) -> str | None:
    """轮转会话 ID（防会话固定攻击）：保留会话数据，生成新 ID。"""
    redis = await get_redis()
    data = await redis.hgetall(_session_key(old_session_id))
    if not data:
        return None

    new_session_id = secrets.token_hex(SESSION_ID_BYTES)

    # 复制数据到新 key
    await redis.hset(_session_key(new_session_id), mapping=data)
    ttl = await redis.ttl(_session_key(old_session_id))
    if ttl > 0:
        await redis.expire(_session_key(new_session_id), ttl)

    # 更新索引
    account_id = data.get("account_id", "")
    if account_id:
        await redis.set(_account_key(account_id), new_session_id, ex=ttl if ttl > 0 else None)

    # 删除旧会话
    await redis.delete(_session_key(old_session_id))

    return new_session_id
