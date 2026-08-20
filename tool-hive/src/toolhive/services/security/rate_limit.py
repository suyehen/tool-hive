"""登录失败统计与限流。"""

from __future__ import annotations

from toolhive.config import AdminSecuritySettings
from toolhive.infrastructure.redis import get_redis

# ── Redis key 前缀 ──
_ACCOUNT_FAIL_PREFIX: str = "login_fail:account:"
_IP_FAIL_PREFIX: str = "login_fail:ip:"

_admin_security = AdminSecuritySettings()


def configure_security(admin_security: AdminSecuritySettings) -> None:
    """启动阶段绑定管理安全配置分区。"""
    global _admin_security
    _admin_security = admin_security


async def record_login_failure(account_id: str | None, source_ip: str) -> None:
    """记录登录失败（账号 + IP 维度）。"""
    redis = await get_redis()
    window_sec = _admin_security.login_failure_window_minutes * 60

    async with redis.pipeline(transaction=True) as pipe:
        if account_id:
            pipe.incr(f"{_ACCOUNT_FAIL_PREFIX}{account_id}")
            pipe.expire(f"{_ACCOUNT_FAIL_PREFIX}{account_id}", window_sec)
        pipe.incr(f"{_IP_FAIL_PREFIX}{source_ip}")
        pipe.expire(f"{_IP_FAIL_PREFIX}{source_ip}", window_sec)
        await pipe.execute()


async def clear_login_failures(account_id: str, source_ip: str) -> None:
    """登录成功后清除失败计数。"""
    redis = await get_redis()
    await redis.delete(
        f"{_ACCOUNT_FAIL_PREFIX}{account_id}",
        f"{_IP_FAIL_PREFIX}{source_ip}",
    )
