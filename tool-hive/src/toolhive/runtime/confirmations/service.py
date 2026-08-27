"""运行侧高风险执行确认服务：申请、一次性令牌校验与过期处理。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import ConfirmationStatus
from toolhive.infrastructure.transactions import transactional
from toolhive.models.runtime_confirmation import RuntimeConfirmation
from toolhive.runtime.errors import (
    RUNTIME_CONFIRMATION_INVALID,
    RuntimeApiError,
)
from toolhive.runtime.tracing.service import TraceService

DEFAULT_CONFIRMATION_TTL_SECONDS = 300


def hash_token(token: str) -> str:
    """令牌 SHA-256 哈希（数据库只存哈希，不存明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ConfirmationService:
    """确认申请与一次性消费。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @transactional()
    async def request_confirmation(
        self,
        *,
        system_id: str,
        tool_id: str,
        tool_code: str,
        version_id: str | None = None,
        ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS,
        trace_id: str | None = None,
    ) -> tuple[RuntimeConfirmation, str]:
        """创建确认申请并返回一次性令牌（明文仅返回一次）。"""
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        record = RuntimeConfirmation(
            system_id=system_id,
            tool_id=tool_id,
            version_id=version_id,
            tool_code=tool_code,
            token_hash=hash_token(token),
            status=ConfirmationStatus.PENDING,
            expires_at=now + timedelta(seconds=ttl_seconds),
            trace_id=trace_id,
            create_time=now,
        )
        self.db.add(record)
        await self.db.flush()
        await TraceService.log_event(
            trace_id=trace_id or record.id,
            system_id=system_id,
            action="runtime.confirmation",
            status="success",
            summary={
                "confirmation_id": record.id,
                "tool_code": tool_code,
                "status": ConfirmationStatus.PENDING,
            },
        )
        return record, token

    @transactional()
    async def verify_confirmation(
        self,
        *,
        system_id: str,
        confirmation_id: str,
        token: str,
        trace_id: str | None = None,
    ) -> RuntimeConfirmation:
        """一次性校验确认令牌；失败或重放抛出 RUNTIME_CONFIRMATION_INVALID。"""
        record = await self.db.get(RuntimeConfirmation, confirmation_id)
        if record is None or record.system_id != system_id:
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID, "确认申请不存在", 400,
            )
        now = datetime.now(UTC)
        if record.status != ConfirmationStatus.PENDING:
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID,
                "确认令牌已使用或已失效",
                400,
            )
        if record.expires_at <= now:
            record.status = ConfirmationStatus.EXPIRED
            record.update_time = now
            await self.db.flush()
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID, "确认令牌已过期", 400,
            )
        if not secrets.compare_digest(record.token_hash, hash_token(token)):
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID, "确认令牌无效", 400,
            )
        record.status = ConfirmationStatus.CONSUMED
        record.consumed_at = now
        record.update_time = now
        await self.db.flush()
        await TraceService.log_event(
            trace_id=trace_id or record.trace_id or record.id,
            system_id=system_id,
            action="runtime.confirmation",
            status="success",
            summary={
                "confirmation_id": record.id,
                "tool_code": record.tool_code,
                "status": ConfirmationStatus.CONSUMED,
            },
        )
        return record
