"""登录失败与验证码挑战限流测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
