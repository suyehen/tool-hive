"""登录失败与验证码挑战限流测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.services.security import rate_limit


@pytest.fixture(autouse=True)
def _configure_security() -> None:
    """固定使用默认安全配置。"""
    rate_limit.configure_security(AdminSecuritySettings())


async def test_is_ip_blocked_below_threshold() -> None:
    """窗口内失败次数低于阈值时不拦截。"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="3")
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.is_ip_blocked("1.2.3.4") is False


async def test_is_ip_blocked_at_threshold() -> None:
    """窗口内失败次数达到阈值时拦截。"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value="5")
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.is_ip_blocked("1.2.3.4") is True


async def test_is_ip_blocked_no_record() -> None:
    """无失败记录时不拦截。"""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.is_ip_blocked("1.2.3.4") is False


async def test_check_captcha_challenge_limit_allows_within_limit() -> None:
    """验证码挑战次数未超限时允许。"""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=10)
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.check_captcha_challenge_limit("1.2.3.4") is True
    redis.expire.assert_not_awaited()


async def test_check_captcha_challenge_limit_rejects_over_limit() -> None:
    """验证码挑战次数超限时拒绝。"""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=11)
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.check_captcha_challenge_limit("1.2.3.4") is False


async def test_check_captcha_challenge_limit_sets_expire_on_first() -> None:
    """首次请求时设置一分钟过期。"""
    redis = AsyncMock()
    redis.incr = AsyncMock(return_value=1)
    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        assert await rate_limit.check_captcha_challenge_limit("1.2.3.4") is True
    redis.expire.assert_awaited_once_with("captcha_challenge:1.2.3.4", 60)


async def test_record_login_failure_tracks_account_ips() -> None:
    """登录失败时记录账号关联的失败来源 IP。"""
    redis = AsyncMock()
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)

    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        await rate_limit.record_login_failure("acc-1", "1.2.3.4")

    sadd_calls = [c.args for c in pipe.sadd.call_args_list]
    assert ("login_fail:account_ips:acc-1", "1.2.3.4") in sadd_calls
    expire_keys = [c.args[0] for c in pipe.expire.call_args_list]
    assert "login_fail:account_ips:acc-1" in expire_keys


async def test_clear_account_failure_ips_deletes_ip_counters() -> None:
    """解锁时清除账号关联失败 IP 的限流计数与集合。"""
    redis = AsyncMock()
    redis.smembers = AsyncMock(return_value={"1.2.3.4", "5.6.7.8"})
    pipe = MagicMock()
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    pipe.execute = AsyncMock()
    redis.pipeline = MagicMock(return_value=pipe)

    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        await rate_limit.clear_account_failure_ips("acc-1")

    delete_keys = [c.args[0] for c in pipe.delete.call_args_list]
    assert "login_fail:ip:1.2.3.4" in delete_keys
    assert "login_fail:ip:5.6.7.8" in delete_keys
    assert "login_fail:account_ips:acc-1" in delete_keys


async def test_clear_login_failures_removes_account_ips() -> None:
    """登录成功时一并清除账号失败 IP 集合。"""
    redis = AsyncMock()
    redis.delete = AsyncMock()

    with patch("toolhive.services.security.rate_limit.get_redis", return_value=redis):
        await rate_limit.clear_login_failures("acc-1", "1.2.3.4")

    keys = redis.delete.call_args.args
    assert "login_fail:account_ips:acc-1" in keys
