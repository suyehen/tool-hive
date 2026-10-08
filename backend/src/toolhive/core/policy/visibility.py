"""可见集合专用 Outbox 消费入口；调用方提交事务后才算 ACK。"""

from datetime import UTC, datetime, timedelta

from redis.exceptions import RedisError
from sqlalchemy import or_, select

from toolhive.core.domain.models import OutboxEvent
from toolhive.core.policy.authorization import AuthorizationService
from toolhive.core.policy.degradation import Mechanism, dependency_failed


async def consume_invalidations(service: AuthorizationService, *, limit: int = 100) -> int:
    """在短事务中调用；SKIP LOCKED 支持多 worker，Redis ACK 丢失可重复 INCR。

    只消费 visibility.invalidate，不代替 H 的通用 Outbox 调度器。
    """
    if not 1 <= limit <= 1000:
        raise ValueError("消费批量无效")
    now = datetime.now(UTC)
    events = (
        await service.session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_type == "visibility.invalidate",
                OutboxEvent.status.in_(["PENDING", "RETRY"]),
                or_(OutboxEvent.next_retry_at.is_(None), OutboxEvent.next_retry_at <= now),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    succeeded = 0
    for event in events:
        try:
            await service.invalidate(
                [event.object_id] if event.object_type == "principal" else None
            )
        except RedisError:
            dependency_failed(Mechanism.VISIBILITY)
            event.status = "RETRY"
            event.next_retry_at = now + timedelta(seconds=5)
            event.last_error = "Redis unavailable"
        else:
            event.status = "SUCCEEDED"
            event.last_error = None
            succeeded += 1
        event.attempts += 1
    await service.session.flush()
    return succeeded
