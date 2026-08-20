"""图形验证码服务测试（H04）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.services.security import captcha as captcha_service


@pytest.fixture(autouse=True)
def _configure_security() -> None:
    """固定使用默认安全配置。"""
    captcha_service.configure_security(AdminSecuritySettings())


async def test_create_captcha_challenge_returns_structure() -> None:
    """挑战返回验证码标识、PNG 图片与有效期，答案写入 Redis。"""
    redis = AsyncMock()
    with patch("toolhive.services.security.captcha.get_redis", return_value=redis):
        result = await captcha_service.create_captcha_challenge()

    assert set(result) == {"captcha_id", "image", "expires_in_seconds"}
    assert result["expires_in_seconds"] == 300
    assert result["image"].startswith("data:image/png;base64,")
    assert redis.set.await_count == 1
    key, code = redis.set.await_args.args
    ex = redis.set.await_args.kwargs["ex"]
    assert key.startswith("captcha:")
    assert len(code) == 4
    assert ex == 300


async def test_consume_captcha_success() -> None:
    """答案正确时返回 True，并一次性消费。"""
    redis = AsyncMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=["AB12", 1])
    pipe.get = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    redis.pipeline = MagicMock(return_value=pipe)

    with patch("toolhive.services.security.captcha.get_redis", return_value=redis):
        ok = await captcha_service.consume_captcha("cid-1", "AB12")

    assert ok is True
    pipe.get.assert_called_once_with("captcha:cid-1")
    pipe.delete.assert_called_once_with("captcha:cid-1")


async def test_consume_captcha_wrong_answer() -> None:
    """答案错误时返回 False，且同样消费该挑战。"""
    redis = AsyncMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=["AB12", 1])
    pipe.get = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    redis.pipeline = MagicMock(return_value=pipe)

    with patch("toolhive.services.security.captcha.get_redis", return_value=redis):
        ok = await captcha_service.consume_captcha("cid-1", "XYZZ")

    assert ok is False
    pipe.delete.assert_called_once()


async def test_consume_captcha_missing_or_replayed() -> None:
    """挑战不存在或已被消费（重放）时返回 False。"""
    redis = AsyncMock()
    pipe = AsyncMock()
    pipe.execute = AsyncMock(return_value=[None, 0])
    pipe.get = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    redis.pipeline = MagicMock(return_value=pipe)

    with patch("toolhive.services.security.captcha.get_redis", return_value=redis):
        ok = await captcha_service.consume_captcha("cid-gone", "AB12")

    assert ok is False
