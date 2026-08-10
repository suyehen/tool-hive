"""管理账号测试 fixtures。"""

from __future__ import annotations

import pytest

from toolhive.models.management_account import ManagementAccount


@pytest.fixture
def sample_account() -> ManagementAccount:
    """返回一个构建好的 ManagementAccount 实例（未持久化）。"""
    return ManagementAccount(
        id="abc123def456",
        username="test_admin",
        password_hash="$argon2id$...",
        external_user_id="EMP001",
        status="enabled",
        login_failures=0,
        must_change_password=False,
    )


@pytest.fixture
def disabled_account() -> ManagementAccount:
    """返回一个禁用状态的账号。"""
    return ManagementAccount(
        id="disabled001",
        username="disabled_user",
        password_hash="$argon2id$...",
        status="disabled",
        login_failures=0,
        must_change_password=False,
    )
