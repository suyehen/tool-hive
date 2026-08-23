"""基础管理审计服务。

职责：追加式写入管理操作审计记录，成功审计随业务事务提交，
失败审计通过独立事务立即提交（避免被业务回滚吞掉）。
敏感字段（密码、密钥、Token 等）在写入前脱敏。
"""

from __future__ import annotations

import contextvars
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.infrastructure import database
from toolhive.models.management_audit_log import ManagementAuditLog

# 摘要键名包含以下片段时视为敏感字段，写入前替换为 ***
_SENSITIVE_KEY_HINTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "public_key",
    "private_key",
    "credential",
    "old_password",
    "new_password",
)

# 当前请求操作人（由 require_operation 依赖注入），CLI/系统初始化时为空
_current_actor: contextvars.ContextVar[dict[str, str | None]] = (
    contextvars.ContextVar("toolhive_audit_actor", default={})
)


def set_audit_actor(account_id: str | None, account_name: str | None) -> None:
    """设置当前请求的操作人（管理 API 依赖阶段调用）。"""
    _current_actor.set({"account_id": account_id, "account_name": account_name})


def get_audit_actor() -> dict[str, str | None]:
    """读取当前请求操作人。"""
    return _current_actor.get()


def get_current_operator_id() -> str | None:
    """读取当前请求操作人 ID（管理 API 依赖阶段注入）。"""
    return get_audit_actor().get("account_id")


def _sanitize_value(key: str, value: Any) -> Any:
    lower = key.lower()
    if any(hint in lower for hint in _SENSITIVE_KEY_HINTS):
        return "***"
    return value


def sanitize_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """递归脱敏摘要中的敏感字段。"""
    if summary is None:
        return None
    result: dict[str, Any] = {}
    for key, value in summary.items():
        if isinstance(value, dict):
            result[key] = sanitize_summary(value)
        elif isinstance(value, list):
            result[key] = [
                sanitize_summary(item) if isinstance(item, dict)
                else _sanitize_value(key, item)
                for item in value
            ]
        else:
            result[key] = _sanitize_value(key, value)
    return result


def _dump(summary: dict[str, Any] | None) -> str | None:
    if summary is None:
        return None
    return json.dumps(sanitize_summary(summary), ensure_ascii=False, sort_keys=True)


class AuditService:
    """审计写入服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    def add_record(
        self,
        action: str,
        object_type: str,
        object_id: str | None = None,
        actor_account_id: str | None = None,
        actor_account_name: str | None = None,
        actor_system_id: str | None = None,
        before_summary: dict[str, Any] | None = None,
        after_summary: dict[str, Any] | None = None,
        reason: str | None = None,
        result: str = "success",
        trace_id: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """在当前会话追加一条审计记录（随外层事务提交/回滚）。"""
        actor = get_audit_actor()
        record = ManagementAuditLog(
            actor_account_id=(
                actor_account_id if actor_account_id is not None
                else actor.get("account_id")
            ),
            actor_account_name=(
                actor_account_name if actor_account_name is not None
                else actor.get("account_name")
            ),
            actor_system_id=actor_system_id,
            object_type=object_type,
            object_id=object_id,
            action=action,
            before_summary=_dump(before_summary),
            after_summary=_dump(after_summary),
            reason=reason,
            result=result,
            trace_id=trace_id,
            source_ip=source_ip,
        )
        self.db.add(record)

    @classmethod
    async def record_standalone(
        cls,
        action: str,
        object_type: str,
        object_id: str | None = None,
        actor_account_id: str | None = None,
        actor_account_name: str | None = None,
        actor_system_id: str | None = None,
        before_summary: dict[str, Any] | None = None,
        after_summary: dict[str, Any] | None = None,
        reason: str | None = None,
        result: str = "failure",
        trace_id: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """使用独立事务立即写入审计记录（失败审计专用）。"""
        actor = get_audit_actor()
        async with database.async_session_factory() as db:
            record = ManagementAuditLog(
                actor_account_id=(
                    actor_account_id if actor_account_id is not None
                    else actor.get("account_id")
                ),
                actor_account_name=(
                    actor_account_name if actor_account_name is not None
                    else actor.get("account_name")
                ),
                actor_system_id=actor_system_id,
                object_type=object_type,
                object_id=object_id,
                action=action,
                before_summary=_dump(before_summary),
                after_summary=_dump(after_summary),
                reason=reason,
                result=result,
                trace_id=trace_id,
                source_ip=source_ip,
            )
            db.add(record)
            await db.commit()
