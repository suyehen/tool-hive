"""图形验证码服务：挑战生成、Redis 存储、一次性校验。

验证码答案只保存在 Redis，TTL 由 ``captcha_ttl_seconds`` 控制；
每次校验（无论成功或失败）都会消费对应挑战，禁止重放。
"""

from __future__ import annotations

import secrets
from base64 import b64encode
from hmac import compare_digest
from typing import Any

from captcha.image import ImageCaptcha

from toolhive.config import AdminSecuritySettings
from toolhive.infrastructure.redis import get_redis

# Redis key 前缀
_CAPTCHA_PREFIX: str = "captcha:"

# 排除易混淆字符（0/O、1/I/l、2/Z、5/S、8/B 等），降低人工输入错误率
_ALPHABET: str = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"

_admin_security = AdminSecuritySettings()


def configure_security(admin_security: AdminSecuritySettings) -> None:
    """注入管理侧安全配置（应用启动阶段调用）。"""
    global _admin_security
    _admin_security = admin_security


async def create_captcha_challenge() -> dict[str, Any]:
    """生成新的图形验证码挑战。

    返回验证码标识、PNG 图片（base64 data URI）与有效期（秒）。
    """
    code = "".join(
        secrets.choice(_ALPHABET)
        for _ in range(_admin_security.captcha_code_length)
    )
    captcha_id = secrets.token_urlsafe(24)

    redis = await get_redis()
    await redis.set(
        f"{_CAPTCHA_PREFIX}{captcha_id}",
        code,
        ex=_admin_security.captcha_ttl_seconds,
    )

    image = ImageCaptcha(width=160, height=60)
    buf = image.generate(code)
    image_b64 = b64encode(buf.getvalue()).decode("ascii")

    return {
        "captcha_id": captcha_id,
        "image": f"data:image/png;base64,{image_b64}",
        "expires_in_seconds": _admin_security.captcha_ttl_seconds,
    }


async def consume_captcha(captcha_id: str, code: str) -> bool:
    """一次性校验验证码；无论正确与否都会消费该挑战，不可重放。

    校验不区分大小写，并忽略输入首尾空白，降低人工输入错误率。
    """
    redis = await get_redis()
    key = f"{_CAPTCHA_PREFIX}{captcha_id}"
    pipe = redis.pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    stored, _deleted = await pipe.execute()
    if stored is None:
        return False
    # 统一小写并去除首尾空白后比较，避免大小写误输导致登录失败
    return compare_digest(stored.lower(), code.strip().lower())
