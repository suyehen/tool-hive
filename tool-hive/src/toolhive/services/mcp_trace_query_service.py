"""MCP 渠道调用记录查询服务（管理端）。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.models.runtime_trace_log import RuntimeTraceLog


class McpTraceQueryService:
    """按 trace 分组查询 MCP 渠道 Trace 事件（channel=mcp）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_records(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        client_id: str | None = None,
    ) -> tuple[list[RuntimeTraceLog], int]:
        """分页返回每个 trace 最近一次事件作为列表摘要。"""
        max_occurred = (
            select(
                RuntimeTraceLog.trace_id.label("trace_id"),
                func.max(RuntimeTraceLog.occurred_at).label("last_at"),
            )
            .where(RuntimeTraceLog.channel == "mcp")
        )
        if status:
            max_occurred = max_occurred.where(RuntimeTraceLog.status == status)
        if client_id:
            max_occurred = max_occurred.where(
                RuntimeTraceLog.mcp_client_id == client_id,
            )
        grouped = max_occurred.group_by(
            RuntimeTraceLog.trace_id,
        ).subquery()
        total = await self.db.scalar(select(func.count()).select_from(grouped))
        summary_rows = await self.db.execute(
            select(RuntimeTraceLog)
            .join(
                grouped,
                (RuntimeTraceLog.trace_id == grouped.c.trace_id)
                & (RuntimeTraceLog.occurred_at == grouped.c.last_at),
            )
            .order_by(RuntimeTraceLog.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(summary_rows.scalars().all()), total or 0

    async def get_events(self, trace_id: str) -> list[RuntimeTraceLog]:
        """返回指定 trace 的完整事件链。"""
        rows = await self.db.execute(
            select(RuntimeTraceLog)
            .where(
                RuntimeTraceLog.trace_id == trace_id,
                RuntimeTraceLog.channel == "mcp",
            )
            .order_by(RuntimeTraceLog.occurred_at)
        )
        return list(rows.scalars().all())
