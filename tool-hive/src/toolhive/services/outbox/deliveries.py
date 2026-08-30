"""Outbox 投递目标实现。

每个投递目标独立执行、独立重试；当前一期没有业务事件源，
redis/chroma 投递为骨架实现，具体投递规则随业务事件接入。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from toolhive.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)


class DeliveryError(Exception):
    """可重试的投递失败（网络、临时不可用等）。"""


class DeterministicDeliveryError(Exception):
    """确定性投递错误（未知目标、未知事件类型等），有限重试后进入 DEAD。"""


class DeliveryTarget(ABC):
    """投递目标接口。"""

    name: str

    @abstractmethod
    async def deliver(self, event: OutboxEvent) -> None:
        """执行投递；失败抛出 ``DeliveryError`` 或 ``DeterministicDeliveryError``。"""


class RedisCacheDelivery(DeliveryTarget):
    """Redis 普通缓存失效投递。

    普通缓存失效使用可重复的删除操作；具体失效 key 规则随业务事件接入。
    """

    name = "redis"

    async def deliver(self, event: OutboxEvent) -> None:
        logger.info("outbox delivery target=redis event=%s", event.event_id)


class ChromaIndexDelivery(DeliveryTarget):
    """Chroma 派生索引投递。

    所有 Chroma 写入只允许通过本投递执行；``catalog.tool.changed`` /
    ``catalog.version.changed`` 驱动工具文档 upsert/delete；
    provider/capability 事件不影响工具索引内容，跳过。
    """

    name = "chroma"

    async def deliver(self, event: OutboxEvent) -> None:
        from toolhive.infrastructure import database
        from toolhive.infrastructure.vector_index import VectorIndexError
        from toolhive.runtime.retrieval.embedding import EmbeddingUnavailableError
        from toolhive.runtime.retrieval.service import RetrievalService

        if event.event_type in (
            "catalog.provider.changed",
            "catalog.capability.changed",
        ):
            logger.info(
                "chroma delivery skip event=%s type=%s",
                event.event_id, event.event_type,
            )
            return
        if event.event_type not in (
            "catalog.tool.changed",
            "catalog.version.changed",
        ):
            raise DeterministicDeliveryError(
                f"未知事件类型: {event.event_type}"
            )
        if event.event_type == "catalog.version.changed":
            tool_id = (event.payload or {}).get("tool_id")
        else:
            tool_id = event.object_id
        if not tool_id:
            raise DeterministicDeliveryError("事件缺少 tool_id")
        try:
            async with database.async_session_factory() as session:
                await RetrievalService(session).sync_tool(tool_id)
            logger.info(
                "chroma delivery succeeded event=%s tool_id=%s",
                event.event_id, tool_id,
            )
        except (VectorIndexError, EmbeddingUnavailableError) as exc:
            raise DeliveryError(f"索引同步失败: {exc}") from exc
        except Exception as exc:
            logger.exception("chroma delivery failed event=%s", event.event_id)
            raise DeliveryError(str(exc)[:500]) from exc


TARGETS: dict[str, DeliveryTarget] = {
    target.name: target
    for target in (RedisCacheDelivery(), ChromaIndexDelivery())
}
