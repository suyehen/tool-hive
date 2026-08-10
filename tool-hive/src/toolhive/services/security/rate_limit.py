"""登录限流与验证码触发。"""

from __future__ import annotations

from redis.asyncio import Redis

from toolhive.config import settings
from toolhive.infrastructure.redis import get_redis

# ── Redis key 前缀 ──
_ACCOUNT_FAIL_PREFIX: str = "login_fail:account:"
_IP_FAIL_PREFIX: str = "login_fail:ip:"


async def check_captcha_required(account_id: str | None, source_ip: str) -> bool:
    """检查是否需要验证码。

    规则：账号或 IP 在窗口内失败 >= captcha_trigger_failures 次。
    """
    redis = await get_redis()
    threshold = settings.captcha_trigger_failures
    window_min = settings.captcha_trigger_window_minutes

    checks: list[bool] = []

    if account_id:
        count = await redis.get(f"{_ACCOUNT_FAIL_PREFIX}{account_id}")
        checks.append(int(count or 0) >= threshold)

    ip_count = await redis.get(f"{_IP_FAIL_PREFIX}{source_ip}")
    checks.append(int(ip_count or 0) >= threshold)

    return any(checks)


async def record_login_failure(account_id: str | None, source_ip: str) -> None:
    """记录登录失败（账号 + IP 维度）。"""
    redis = await get_redis()
    window_sec = settings.captcha_trigger_window_minutes * 60

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
