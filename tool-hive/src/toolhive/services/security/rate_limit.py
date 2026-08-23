"""登录失败统计与限流。"""

from __future__ import annotations

from toolhive.config import AdminSecuritySettings
from toolhive.infrastructure.redis import get_redis

# ── Redis key 前缀 ──
_ACCOUNT_FAIL_PREFIX: str = "login_fail:account:"
_IP_FAIL_PREFIX: str = "login_fail:ip:"
_ACCOUNT_IP_PREFIX: str = "login_fail:account_ips:"
_CAPTCHA_CHALLENGE_PREFIX: str = "captcha_challenge:"

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
            # 记录该账号失败来源 IP，供管理员解锁时一并清除 IP 限流
            pipe.sadd(f"{_ACCOUNT_IP_PREFIX}{account_id}", source_ip)
            pipe.expire(f"{_ACCOUNT_IP_PREFIX}{account_id}", window_sec)
        pipe.incr(f"{_IP_FAIL_PREFIX}{source_ip}")
        pipe.expire(f"{_IP_FAIL_PREFIX}{source_ip}", window_sec)
        await pipe.execute()


async def clear_login_failures(account_id: str, source_ip: str) -> None:
    """登录成功后清除失败计数。"""
    redis = await get_redis()
    await redis.delete(
        f"{_ACCOUNT_FAIL_PREFIX}{account_id}",
        f"{_IP_FAIL_PREFIX}{source_ip}",
        f"{_ACCOUNT_IP_PREFIX}{account_id}",
    )


async def clear_account_failure_ips(account_id: str) -> None:
    """清除某账号关联的失败来源 IP 限流计数（管理员解锁时调用）。"""
    redis = await get_redis()
    key = f"{_ACCOUNT_IP_PREFIX}{account_id}"
    ips = await redis.smembers(key)
    async with redis.pipeline(transaction=True) as pipe:
        for ip in ips:
            pipe.delete(f"{_IP_FAIL_PREFIX}{ip}")
        pipe.delete(key)
        await pipe.execute()


async def is_ip_blocked(source_ip: str) -> bool:
    """判断来源 IP 在统计窗口内的登录失败次数是否达到阈值。"""
    redis = await get_redis()
    raw = await redis.get(f"{_IP_FAIL_PREFIX}{source_ip}")
    if raw is None:
        return False
    try:
        return int(raw) >= _admin_security.login_max_failures
    except ValueError:
        return False


async def check_captcha_challenge_limit(source_ip: str) -> bool:
    """验证码挑战按来源 IP 限流（每分钟最多 N 次）。

    返回 True 表示允许创建挑战；超过上限返回 False。
    """
    redis = await get_redis()
    key = f"{_CAPTCHA_CHALLENGE_PREFIX}{source_ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= _admin_security.captcha_challenge_max_per_minute
