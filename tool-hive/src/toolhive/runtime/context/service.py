"""ToolContext 辅助服务：声明来源与 Trace 记录。"""

from __future__ import annotations

from toolhive.runtime.context.schema import ToolContext
from toolhive.runtime.tracing.service import TraceService


async def trace_context(
    *,
    trace_id: str,
    system_id: str,
    context: ToolContext,
    source_ip: str | None = None,
) -> None:
    """记录 ToolContext 声明来源与字段存在性（不记录业务身份值）。"""
    await TraceService.log_event(
        trace_id=trace_id,
        system_id=system_id,
        action="runtime.context",
        status="success",
        summary={
            "source": "caller-declared",
            "fields": context.presence_summary(),
        },
        source_ip=source_ip,
    )
