"""认证服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import AuthenticationError
from toolhive.services.auth_service import AuthService


async def test_login_rejects_blocked_ip() -> None:
    """来源 IP 失败次数达阈值时直接拒绝，不消耗验证码。"""
    db = AsyncMock()
    svc = AuthService(db, AdminSecuritySettings())

    with patch(
        "toolhive.services.auth_service.is_ip_blocked",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.services.auth_service.consume_captcha",
        AsyncMock(return_value=True),
    ) as consume:
        with pytest.raises(AuthenticationError) as exc_info:
            await svc.login_password(
                username="admin",
                password="whatever",
                source_ip="1.2.3.4",
                captcha_id="cid-1",
                captcha_code="AB12",
            )
    assert "过于频繁" in str(exc_info.value)
    consume.assert_not_awaited()


async def test_login_rejects_offboarded_account() -> None:
    """已离职账号禁止登录。"""
    account = MagicMock()
    account.status = AccountStatus.OFFBOARDED
    account.is_active.return_value = False
    account.is_locked.return_value = False

    db = AsyncMock()
    svc = AuthService(db, AdminSecuritySettings())
    svc.account_svc.get_by_username = AsyncMock(return_value=account)

    with patch(
        "toolhive.services.auth_service.is_ip_blocked",
        AsyncMock(return_value=False),
    ), patch(
        "toolhive.services.auth_service.consume_captcha",
        AsyncMock(return_value=True),
    ):
        with pytest.raises(AuthenticationError) as exc_info:
            await svc.login_password(
                username="admin",
                password="whatever",
                source_ip="127.0.0.1",
                captcha_id="cid-1",
                captcha_code="AB12",
            )
    assert "已离职" in str(exc_info.value)


async def test_login_rejects_expired_temp_password() -> None:
    """临时密码过期时禁止登录。"""
    account = MagicMock()
    account.status = AccountStatus.ENABLED
    account.is_active.return_value = True
    account.is_locked.return_value = False
    account.auth_state = MagicMock()
    account.auth_state.must_change_password = True
    from datetime import UTC, datetime, timedelta
    account.auth_state.temp_password_expires_at = datetime.now(UTC) - timedelta(minutes=1)

    db = AsyncMock()
    svc = AuthService(db, AdminSecuritySettings())
    svc.account_svc.get_by_username = AsyncMock(return_value=account)
    svc.account_svc.record_login_success = AsyncMock()

    with patch(
        "toolhive.services.auth_service.is_ip_blocked",
        AsyncMock(return_value=False),
    ), patch(
        "toolhive.services.auth_service.consume_captcha",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.services.auth_service.verify_password",
        return_value=(True, False),
    ):
        with pytest.raises(AuthenticationError) as exc_info:
            await svc.login_password(
                username="admin",
                password="whatever",
                source_ip="127.0.0.1",
                captcha_id="cid-1",
                captcha_code="AB12",
            )
    assert "已过期" in str(exc_info.value)
    svc.account_svc.record_login_success.assert_not_awaited()


async def test_login_allows_unexpired_temp_password() -> None:
    """临时密码未过期时允许登录，并保持 must_change_password=True。"""
    from datetime import UTC, datetime, timedelta

    account = MagicMock()
    account.status = AccountStatus.ENABLED
    account.is_active.return_value = True
    account.is_locked.return_value = False
    account.auth_state = MagicMock()
    account.auth_state.must_change_password = True
    account.auth_state.temp_password_expires_at = datetime.now(UTC) + timedelta(hours=1)
    account.auth_state.security_version = 0
    account.id = "acc-1"
    account.username = "admin"

    db = AsyncMock()
    svc = AuthService(db, AdminSecuritySettings())
    svc.account_svc.get_by_username = AsyncMock(return_value=account)
    svc.account_svc.record_login_success = AsyncMock()

    with patch(
        "toolhive.services.auth_service.is_ip_blocked",
        AsyncMock(return_value=False),
    ), patch(
        "toolhive.services.auth_service.consume_captcha",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.services.auth_service.verify_password",
        return_value=(True, False),
    ), patch(
        "toolhive.services.auth_service.clear_login_failures",
        AsyncMock(),
    ), patch(
        "toolhive.services.auth_service.create_session",
        AsyncMock(return_value="sid-1"),
    ), patch(
        "toolhive.services.auth_service.generate_csrf_token",
        return_value="csrf-1",
    ):
        result = await svc.login_password(
            username="admin",
            password="whatever",
            source_ip="127.0.0.1",
            captcha_id="cid-1",
            captcha_code="AB12",
        )

    assert result.account is account
    assert result.session_id == "sid-1"
