"""会话管理测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_redis():
    """Mock Redis 客户端。"""
    redis = AsyncMock()
    redis.hset = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    redis.expire = AsyncMock()
    redis.ttl = AsyncMock(return_value=3600)
    redis.pipeline = MagicMock()
    return redis


class TestCreateSession:
    """创建会话。"""

    @patch("toolhive.services.security.session.get_redis")
    async def test_returns_session_id(self, mock_get_redis, mock_redis) -> None:
        mock_get_redis.return_value = mock_redis
        mock_redis.get.return_value = None  # 无旧会话

        # Mock pipeline
        mock_pipe = MagicMock()
        mock_pipe.hset = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline.return_value = mock_pipe

        from toolhive.services.security.session import create_session

        session_id = await create_session(
            account_id="test-account-123",
            username="admin",
            security_version=0,
            source_ip="192.168.1.1",
        )
        assert isinstance(session_id, str)
        assert len(session_id) == 64  # 256-bit hex = 64 chars

    @patch("toolhive.services.security.session.get_redis")
    async def test_evicts_old_session(self, mock_get_redis, mock_redis) -> None:
        mock_get_redis.return_value = mock_redis
        mock_redis.get.return_value = "old-session-id"

        mock_pipe = MagicMock()
        mock_pipe.hset = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.set = MagicMock()
        mock_pipe.execute = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=None)
        mock_redis.pipeline.return_value = mock_pipe

        from toolhive.services.security.session import create_session

        await create_session(
            account_id="test-account-123",
            username="admin",
            security_version=1,
            source_ip="10.0.0.1",
        )
        # 应删除旧会话
        mock_redis.delete.assert_called_once()


class TestGetSession:
    """读取会话。"""

    @patch("toolhive.services.security.session.get_redis")
    async def test_returns_none_for_empty_data(self, mock_get_redis, mock_redis) -> None:
        mock_get_redis.return_value = mock_redis
        mock_redis.hgetall.return_value = {}

        from toolhive.services.security.session import get_session

        result = await get_session("nonexistent")
        assert result is None

    @patch("toolhive.services.security.session.get_redis")
    async def test_returns_session_data(self, mock_get_redis, mock_redis) -> None:
        import time
        now = int(time.time())
        mock_get_redis.return_value = mock_redis
        mock_redis.hgetall.return_value = {
            "account_id": "acc-123",
            "username": "admin",
            "security_version": "0",
            "source_ip": "1.2.3.4",
            "created_at": str(now - 100),
            "last_activity": str(now - 10),
            "expires_at": str(now + 3600),
        }

        from toolhive.services.security.session import get_session

        result = await get_session("valid-session")
        assert result is not None
        assert result.account_id == "acc-123"
        assert result.username == "admin"
        assert result.security_version == "0"


class TestRevokeSession:
    """撤销会话。"""

    @patch("toolhive.services.security.session.get_redis")
    async def test_delete_session_and_index(self, mock_get_redis, mock_redis) -> None:
        mock_get_redis.return_value = mock_redis
        mock_redis.hgetall.return_value = {"account_id": "acc-456"}

        from toolhive.services.security.session import revoke_session

        await revoke_session("session-to-delete")
        assert mock_redis.delete.call_count == 2  # session key + account index
