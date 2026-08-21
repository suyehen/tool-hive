"""Outbox 后台投递 Worker。

运行在 ToolHive 同一应用进程内，随应用统一启动/停止：
- 使用 PostgreSQL ``FOR UPDATE SKIP LOCKED`` 领取事件，领取与状态更新使用短事务；
- Redis/Chroma 投递调用在数据库事务之外执行；
- 失败按退避策略重试，超过 ``max_attempts`` 进入 DEAD；
- 投递幂等，支持宕机后锁超时回收。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from toolhive.config import OutboxRetrySettings, OutboxSettings
from toolhive.core.enums import OutboxStatus
from toolhive.infrastructure.database import async_session_factory
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent
from toolhive.services.outbox.deliveries import (
    TARGETS,
    DeliveryError,
    DeterministicDeliveryError,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _compute_next_retry(
    attempt: int, retry_cfg: OutboxRetrySettings,
) -> datetime:
    """按退避策略计算下次重试时间（带随机抖动）。"""
    delay = retry_cfg.initial_delay_seconds * (
        retry_cfg.multiplier ** max(0, attempt - 1)
    )
    delay = min(delay, retry_cfg.max_delay_seconds)
    jitter = delay * retry_cfg.jitter_ratio * random.uniform(-1.0, 1.0)
    return _utcnow() + timedelta(seconds=max(1, delay + jitter))


class OutboxWorker:
    """应用进程内的 Outbox 后台投递任务。"""

    def __init__(self, outbox_settings: OutboxSettings) -> None:
        self._outbox = outbox_settings
        self._instance_id = f"worker_{uuid.uuid4().hex[:12]}"
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def instance_id(self) -> str:
        return self._instance_id

    async def start(self) -> None:
        """启动后台任务（幂等）。"""
        if self._task is not None:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="outbox-worker")
        logger.info("outbox worker started instance=%s", self._instance_id)

    async def stop(self) -> None:
        """停止后台任务。"""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10)
        except TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("outbox worker stopped instance=%s", self._instance_id)

    async def _run(self) -> None:
        poll_interval = self._outbox.poll_interval_ms / 1000
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox worker poll failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=poll_interval,
                )
            except TimeoutError:
                pass

    async def _poll_once(self) -> None:
        event_ids = await self._claim_events()
        if not event_ids:
            return
        semaphore = asyncio.Semaphore(self._outbox.max_concurrency)

        async def _handle(event_id: str) -> None:
            async with semaphore:
                await self._process_event(event_id)

        await asyncio.gather(*(_handle(eid) for eid in event_ids))

    async def _claim_events(self) -> list[str]:
        """领取一批待处理事件（短事务）。"""
        now = _utcnow()
        locked_until = now + timedelta(seconds=self._outbox.lock_timeout_seconds)
        async with async_session_factory() as session:
            # 回收锁超时的 PROCESSING 事件
            await session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.status == OutboxStatus.PROCESSING,
                    OutboxEvent.locked_until < now,
                )
                .values(
                    status=OutboxStatus.PENDING,
                    locked_by=None,
                    locked_until=None,
                    update_time=now,
                )
            )
            result = await session.execute(
                select(OutboxEvent.event_id)
                .where(
                    OutboxEvent.status.in_(
                        (OutboxStatus.PENDING, OutboxStatus.RETRY),
                    ),
                    (
                        (OutboxEvent.next_retry_at.is_(None))
                        | (OutboxEvent.next_retry_at <= now)
                    ),
                )
                .order_by(OutboxEvent.create_time.asc())
                .limit(self._outbox.batch_size)
                .with_for_update(skip_locked=True)
            )
            event_ids = [row[0] for row in result]
            if not event_ids:
                await session.rollback()
                return []
            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.event_id.in_(event_ids))
                .values(
                    status=OutboxStatus.PROCESSING,
                    locked_by=self._instance_id,
                    locked_until=locked_until,
                    update_time=now,
                )
            )
            await session.commit()
            return event_ids

    async def _process_event(self, event_id: str) -> None:
        """处理一个事件的所有投递目标。"""
        async with async_session_factory() as session:
            event = await session.get(OutboxEvent, event_id)
            if event is None:
                return
            deliveries = list(
                (
                    await session.execute(
                        select(OutboxDelivery).where(
                            OutboxDelivery.event_id == event_id,
                        )
                    )
                )
                .scalars()
                .all()
            )

        await asyncio.gather(
            *(self._deliver_one(event, d) for d in deliveries)
        )
        await self._refresh_event_status(event_id)

    async def _deliver_one(
        self, event: OutboxEvent, delivery: OutboxDelivery,
    ) -> None:
        """投递单个目标并更新投递状态（短事务）。"""
        now = _utcnow()
        start = time.perf_counter()
        attempts = delivery.attempts + 1
        max_attempts = self._outbox.max_attempts
        status: str
        last_error: str | None = None

        target = TARGETS.get(delivery.target)
        try:
            if target is None:
                raise DeterministicDeliveryError(
                    f"未知投递目标: {delivery.target}"
                )
            await target.deliver(event)
            status = OutboxStatus.SUCCEEDED
            logger.info(
                "outbox delivery succeeded event=%s target=%s attempt=%s",
                event.event_id, delivery.target, attempts,
            )
        except (DeliveryError, DeterministicDeliveryError) as exc:
            last_error = str(exc)[:500]
            if attempts >= max_attempts:
                status = OutboxStatus.DEAD
                logger.error(
                    "outbox delivery dead event=%s target=%s attempts=%s error=%s",
                    event.event_id, delivery.target, attempts, last_error,
                )
            else:
                status = OutboxStatus.RETRY
                logger.warning(
                    "outbox delivery retry event=%s target=%s attempts=%s error=%s",
                    event.event_id, delivery.target, attempts, last_error,
                )
        except Exception as exc:  # 未知异常按可重试失败处理
            last_error = f"unexpected: {str(exc)[:500]}"
            if attempts >= max_attempts:
                status = OutboxStatus.DEAD
                logger.error(
                    "outbox delivery dead event=%s target=%s attempts=%s error=%s",
                    event.event_id, delivery.target, attempts, last_error,
                )
            else:
                status = OutboxStatus.RETRY
                logger.warning(
                    "outbox delivery retry event=%s target=%s attempts=%s error=%s",
                    event.event_id, delivery.target, attempts, last_error,
                )

        async with async_session_factory() as session:
            await session.execute(
                update(OutboxDelivery)
                .where(OutboxDelivery.delivery_id == delivery.delivery_id)
                .values(
                    status=status,
                    attempts=attempts,
                    last_error=last_error,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    worker_instance=self._instance_id,
                    update_time=now,
                )
            )
            await session.commit()

    async def _refresh_event_status(self, event_id: str) -> None:
        """根据所有投递状态聚合更新事件状态。"""
        now = _utcnow()
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        OutboxDelivery.status,
                        OutboxDelivery.attempts,
                    ).where(OutboxDelivery.event_id == event_id)
                )
            ).all()
            if not rows:
                await session.rollback()
                return

            statuses = [r[0] for r in rows]
            if any(
                s in (
                    OutboxStatus.PENDING,
                    OutboxStatus.PROCESSING,
                    OutboxStatus.RETRY,
                )
                for s in statuses
            ):
                event_status = OutboxStatus.RETRY
            elif all(s == OutboxStatus.SUCCEEDED for s in statuses):
                event_status = OutboxStatus.SUCCEEDED
            else:
                event_status = OutboxStatus.DEAD

            next_retry_at: datetime | None = None
            if event_status == OutboxStatus.RETRY:
                max_attempt = max(r[1] for r in rows)
                next_retry_at = _compute_next_retry(max_attempt, self._outbox.retry)

            await session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.event_id == event_id)
                .values(
                    status=event_status,
                    next_retry_at=next_retry_at,
                    locked_by=None,
                    locked_until=None,
                    update_time=now,
                )
            )
            await session.commit()
