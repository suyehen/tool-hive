"""运行侧高风险确认服务测试：申请、一次性校验、过期与重放。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.core.enums import ConfirmationStatus
from toolhive.models.runtime_confirmation import RuntimeConfirmation
from toolhive.runtime.confirmations.service import (
    ConfirmationService,
    hash_token,
)
from toolhive.runtime.errors import RUNTIME_CONFIRMATION_INVALID, RuntimeApiError
from toolhive.runtime.tracing.service import TraceService


@pytest.fixture(autouse=True)
def _patch_trace() -> None:
    """确认测试不落真实 Trace，避免异步 mock 告警。"""
    with patch.object(TraceService, "log_event", new=AsyncMock()):
        yield


def _record(status: str = ConfirmationStatus.PENDING, **kwargs) -> RuntimeConfirmation:
    defaults = dict(
        id="confirm-1",
        system_id="sys_1",
        tool_id="tool-1",
        tool_code="math.basic.calculator",
        token_hash=hash_token("token-abc"),
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        create_time=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return RuntimeConfirmation(**defaults)


async def test_request_returns_record_and_token() -> None:
    """申请成功返回记录与一次性令牌（明文只在本次返回）。"""
    db = AsyncMock()
    db.add = MagicMock()
    svc = ConfirmationService(db)
    record, token = await svc.request_confirmation(
        system_id="sys_1",
        tool_id="tool-1",
        tool_code="math.basic.calculator",
        trace_id="trace-1",
    )
    assert isinstance(record, RuntimeConfirmation)
    assert token
    assert record.token_hash == hash_token(token)
    assert record.token_hash != token
    assert record.status == ConfirmationStatus.PENDING


async def test_verify_consumes_token_once() -> None:
    """令牌校验通过后一次性消费。"""
    record = _record()
    db = AsyncMock()
    db.get = AsyncMock(return_value=record)
    db.add = AsyncMock()
    svc = ConfirmationService(db)
    result = await svc.verify_confirmation(
        system_id="sys_1",
        confirmation_id="confirm-1",
        token="token-abc",
    )
    assert result.status == ConfirmationStatus.CONSUMED
    assert result.consumed_at is not None


async def test_verify_rejects_replay() -> None:
    """已消费令牌再次使用被拒绝。"""
    record = _record(status=ConfirmationStatus.CONSUMED)
    db = AsyncMock()
    db.get = AsyncMock(return_value=record)
    svc = ConfirmationService(db)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.verify_confirmation(
            system_id="sys_1",
            confirmation_id="confirm-1",
            token="token-abc",
        )
    assert exc_info.value.code == RUNTIME_CONFIRMATION_INVALID


async def test_verify_rejects_expired() -> None:
    """过期令牌被拒绝并标记 expired。"""
    record = _record(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    db = AsyncMock()
    db.get = AsyncMock(return_value=record)
    db.add = AsyncMock()
    svc = ConfirmationService(db)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.verify_confirmation(
            system_id="sys_1",
            confirmation_id="confirm-1",
            token="token-abc",
        )
    assert exc_info.value.code == RUNTIME_CONFIRMATION_INVALID
    assert record.status == ConfirmationStatus.EXPIRED


async def test_verify_rejects_wrong_token() -> None:
    """错误令牌被拒绝。"""
    record = _record()
    db = AsyncMock()
    db.get = AsyncMock(return_value=record)
    svc = ConfirmationService(db)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.verify_confirmation(
            system_id="sys_1",
            confirmation_id="confirm-1",
            token="wrong-token",
        )
    assert exc_info.value.code == RUNTIME_CONFIRMATION_INVALID


async def test_verify_rejects_wrong_system() -> None:
    """其他调用系统的确认申请不可用。"""
    record = _record()
    db = AsyncMock()
    db.get = AsyncMock(return_value=record)
    svc = ConfirmationService(db)
    with pytest.raises(RuntimeApiError) as exc_info:
        await svc.verify_confirmation(
            system_id="sys_other",
            confirmation_id="confirm-1",
            token="token-abc",
        )
    assert exc_info.value.code == RUNTIME_CONFIRMATION_INVALID
