"""事务装饰器回滚行为测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from toolhive.core.exceptions import ValidationError
from toolhive.infrastructure.transactions import transactional


class _FakeService:
    def __init__(self) -> None:
        self.db = AsyncMock()

    @transactional()
    async def delete_then_raise(self) -> None:
        await self.db.delete("row-1")
        raise ValidationError("boom")


class _FakeServiceOk:
    def __init__(self) -> None:
        self.db = AsyncMock()

    @transactional()
    async def write_ok(self) -> None:
        await self.db.delete("row-1")


async def test_transactional_rolls_back_on_error() -> None:
    """写操作抛出异常时回滚且不提交。"""
    svc = _FakeService()

    with pytest.raises(ValidationError):
        await svc.delete_then_raise()

    svc.db.rollback.assert_awaited_once()
    svc.db.commit.assert_not_awaited()


async def test_transactional_commits_on_success() -> None:
    """写操作正常结束时提交。"""
    svc = _FakeServiceOk()
    await svc.write_ok()

    svc.db.commit.assert_awaited_once()
    svc.db.rollback.assert_not_awaited()
