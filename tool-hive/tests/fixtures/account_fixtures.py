"""管理账号测试 fixtures。"""

from __future__ import annotations

import pytest

from toolhive.models.account_auth_state import ManagementAccountAuthState
from toolhive.models.management_account import ManagementAccount


def _build_account(
    account_id: str,
    account: str,
    status: str,
    *,
    real_name: str = "测试管理员",
    external_user_id: str | None = None,
    must_change_password: bool = False,
) -> ManagementAccount:
    """构造账号及其 1:1 认证状态（未持久化）。"""
    record = ManagementAccount(
        id=account_id,
        account=account,
        real_name=real_name,
        external_user_id=external_user_id,
        status=status,
    )
    record.auth_state = ManagementAccountAuthState(
        account_id=account_id,
        password_hash="$argon2id$...",
        login_failures=0,
        locked_until=None,
        must_change_password=must_change_password,
        temp_password_expires_at=None,
        security_version=0,
    )
    return record


@pytest.fixture
def sample_account() -> ManagementAccount:
    """返回一个构建好的 ManagementAccount 实例（未持久化）。"""
    return _build_account(
        "abc123def456",
        "test_admin",
        "enabled",
        external_user_id="EMP001",
    )


@pytest.fixture
def disabled_account() -> ManagementAccount:
    """返回一个禁用状态的账号。"""
    return _build_account("disabled001", "disabled_user", "disabled")
