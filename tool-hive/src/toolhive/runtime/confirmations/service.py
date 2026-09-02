"""运行侧高风险执行确认服务：申请、一次性令牌校验与过期处理。"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
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
        tool_id: str | None = None,
        version_id: str | None = None,
        trace_id: str | None = None,
    ) -> RuntimeConfirmation:
        """一次性校验确认令牌；失败或重放抛出 RUNTIME_CONFIRMATION_INVALID。"""
        now = datetime.now(UTC)
        # 条件更新原子消费：仅在记录仍为 PENDING、未过期、令牌匹配且
        # （如提供）工具/版本一致时消费成功，杜绝并发双重消费
        conditions = [
            RuntimeConfirmation.id == confirmation_id,
            RuntimeConfirmation.system_id == system_id,
            RuntimeConfirmation.status == ConfirmationStatus.PENDING,
            RuntimeConfirmation.expires_at > now,
            RuntimeConfirmation.token_hash == hash_token(token),
        ]
        if tool_id is not None:
            conditions.append(RuntimeConfirmation.tool_id == tool_id)
        if version_id is not None:
            conditions.append(RuntimeConfirmation.version_id == version_id)
        result = await self.db.execute(
            update(RuntimeConfirmation)
            .where(*conditions)
            .values(
                status=ConfirmationStatus.CONSUMED,
                consumed_at=now,
                update_time=now,
            )
        )
        if result.rowcount != 1:
            # 原子消费未命中：读取记录定位失败原因（用于区分过期/重放/错配）
            record = await self.db.get(RuntimeConfirmation, confirmation_id)
            if record is None or record.system_id != system_id:
                raise RuntimeApiError(
                    RUNTIME_CONFIRMATION_INVALID, "确认申请不存在", 400,
                )
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
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID,
                "确认令牌与目标工具或版本不匹配",
                400,
            )
        record = await self.db.get(RuntimeConfirmation, confirmation_id)
        if record is None:
            raise RuntimeApiError(
                RUNTIME_CONFIRMATION_INVALID, "确认申请不存在", 400,
            )
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
