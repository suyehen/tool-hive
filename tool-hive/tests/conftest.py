"""共享测试 fixture。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_redis() -> AsyncMock:
    """返回一个 AsyncMock 模拟的 Redis 客户端。"""
    return AsyncMock()


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """返回一个 AsyncMock 模拟的数据库会话。"""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _patch_engine():
    """全局 mock 数据库引擎，避免测试时尝试连接真实数据库。"""
    with patch("toolhive.infrastructure.database.engine", MagicMock()):
        with patch("toolhive.infrastructure.database.async_session_factory", MagicMock()):
            yield
