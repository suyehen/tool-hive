"""Outbox Chroma 投递目标测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from toolhive.models.outbox_event import OutboxEvent
from toolhive.services.outbox.deliveries import (
    ChromaIndexDelivery,
    DeliveryError,
    DeterministicDeliveryError,
)


class _FakeFactory:
    """模拟 async_session_factory 的异步上下文管理器。"""

    def __init__(self) -> None:
        self.session = AsyncMock()

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *args):
        return None


def _event(event_type: str, object_id: str = "tool-1", payload: dict | None = None) -> OutboxEvent:
    return OutboxEvent(
        event_id="evt-1",
        event_type=event_type,
        object_type="catalog_tool",
        object_id=object_id,
        payload=payload,
    )


async def test_chroma_delivery_skips_provider_and_capability() -> None:
    """provider/capability 事件不影响工具索引，跳过。"""
    delivery = ChromaIndexDelivery()
    for event_type in ("catalog.provider.changed", "catalog.capability.changed"):
        await delivery.deliver(_event(event_type))


async def test_chroma_delivery_rejects_unknown_type() -> None:
    """未知事件类型进入 DEAD。"""
    delivery = ChromaIndexDelivery()
    with pytest.raises(DeterministicDeliveryError):
        await delivery.deliver(_event("unknown.event"))


async def test_chroma_delivery_syncs_tool() -> None:
    """工具/版本事件调用 RetrievalService.sync_tool。"""
    delivery = ChromaIndexDelivery()
    mock_factory = _FakeFactory()
    with (
        patch(
            "toolhive.infrastructure.database.async_session_factory",
            mock_factory,
        ),
        patch(
            "toolhive.runtime.retrieval.service.RetrievalService"
        ) as retrieval_cls,
    ):
        retrieval_cls.return_value.sync_tool = AsyncMock()
        await delivery.deliver(_event("catalog.version.changed", payload={"tool_id": "tool-1"}))
    retrieval_cls.return_value.sync_tool.assert_awaited_once_with("tool-1")


async def test_chroma_delivery_retries_on_index_error() -> None:
    """索引错误转为可重试 DeliveryError。"""
    delivery = ChromaIndexDelivery()
    mock_factory = _FakeFactory()
    with (
        patch(
            "toolhive.infrastructure.database.async_session_factory",
            mock_factory,
        ),
        patch(
            "toolhive.runtime.retrieval.service.RetrievalService"
        ) as retrieval_cls,
    ):
        retrieval_cls.return_value.sync_tool = AsyncMock(
            side_effect=RuntimeError("chroma down")
        )
        with pytest.raises(DeliveryError):
            await delivery.deliver(_event("catalog.tool.changed"))
