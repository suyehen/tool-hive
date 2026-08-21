"""认证服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import AuthenticationError
from toolhive.services.auth_service import AuthService


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
