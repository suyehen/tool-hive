"""运行侧基础 Trace 服务。"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from toolhive.infrastructure import database
from toolhive.models.runtime_trace_log import RuntimeTraceLog
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RuntimeApiError,
)

logger = logging.getLogger(__name__)

_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_trace_id() -> str:
    """生成新的 Trace ID（UUID hex）。"""
    return uuid.uuid4().hex


def parse_trace_id(raw: str | None) -> str:
    """解析透传 Trace ID：缺失时生成，非法时返回 400 错误。"""
    if raw is None or not raw.strip():
        return new_trace_id()
    value = raw.strip()
    if not _TRACE_ID_PATTERN.match(value):
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID,
            "X-ToolHive-Trace-Id 格式非法（允许 1-64 位字母/数字/下划线/连字符）",
            400,
        )
    return value


class TraceService:
    """运行 Trace 落库：每个事件使用独立事务立即提交，不随业务回滚。"""

    @staticmethod
    async def log_event(
        *,
        trace_id: str,
        action: str,
        status: str = "success",
        system_id: str | None = None,
        error_code: str | None = None,
        summary: dict[str, Any] | None = None,
        source_ip: str | None = None,
    ) -> None:
        """写入一条运行 Trace 记录；失败只记录日志，不影响业务请求。"""
        try:
            async with database.async_session_factory() as session:
                session.add(
                    RuntimeTraceLog(
                        trace_id=trace_id,
                        system_id=system_id,
                        action=action,
                        status=status,
                        error_code=error_code,
                        summary=summary,
                        source_ip=source_ip,
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.error(
                "trace write failed trace_id=%s action=%s error=%s",
                trace_id, action, exc,
            )
