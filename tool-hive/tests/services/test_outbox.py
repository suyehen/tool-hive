"""Outbox Worker 与投递服务测试。"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.config import OutboxRetrySettings
from toolhive.core.exceptions import NotFoundError
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent
from toolhive.services.outbox.service import OutboxService
from toolhive.services.outbox.worker import _compute_next_retry


class TestComputeNextRetry:
    def test_returns_future_time(self) -> None:
        now = datetime.now(UTC)
        value = _compute_next_retry(1, OutboxRetrySettings())
        assert value > now

    def test_delay_grows_with_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(random, "uniform", lambda a, b: 0.0)
        now = datetime.now(UTC)
        d1 = _compute_next_retry(1, OutboxRetrySettings())
        d2 = _compute_next_retry(2, OutboxRetrySettings())
        assert (d1 - now) < (d2 - now)

    def test_delay_capped_at_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(random, "uniform", lambda a, b: 0.0)
        now = datetime.now(UTC)
        value = _compute_next_retry(30, OutboxRetrySettings())
        assert value - now <= timedelta(seconds=1800)


class TestOutboxService:
    def _build_db(self, first_result: object) -> AsyncMock:
        db = AsyncMock()
        exec_mock = AsyncMock()
        exec_mock.return_value.first = MagicMock(return_value=first_result)
        db.execute = exec_mock
        db.flush = AsyncMock()
        return db

    async def test_retry_delivery_updates_status(self) -> None:
        delivery = OutboxDelivery(
            delivery_id="d1",
            event_id="e1",
            target="redis",
            status="DEAD",
            attempts=10,
            last_error="boom",
        )
        event = OutboxEvent(
            event_id="e1",
            event_type="catalog.updated",
            object_type="catalog",
            object_id="c1",
            status="DEAD",
        )
        db = self._build_db((delivery, event))
        svc = OutboxService(db)

        d, e = await svc.retry_delivery("d1")

        assert d.status == "PENDING"
        assert d.last_error is None
        assert e.status == "PENDING"
        assert e.next_retry_at is None
        db.flush.assert_awaited_once()

    async def test_retry_delivery_not_found(self) -> None:
        db = self._build_db(None)
        svc = OutboxService(db)
        with pytest.raises(NotFoundError):
            await svc.retry_delivery("missing")
