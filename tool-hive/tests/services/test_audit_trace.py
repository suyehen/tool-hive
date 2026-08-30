"""管理审计 trace_id 关联与脱敏增强测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from toolhive.models.management_audit_log import ManagementAuditLog
from toolhive.services.audit_service import (
    AuditService,
    get_audit_trace,
    sanitize_summary,
    set_audit_trace,
)


async def test_audit_record_picks_up_context_trace_id() -> None:
    """add_record 默认使用审计上下文中的 trace_id。"""
    set_audit_trace("trace-abc")
    db = MagicMock()
    AuditService(db).add_record(
        action="test.action",
        object_type="test",
        object_id="obj-1",
    )
    record = db.add.call_args.args[0]
    assert isinstance(record, ManagementAuditLog)
    assert record.trace_id == "trace-abc"


async def test_audit_trace_invalid_ignored() -> None:
    """非法或缺失 trace_id 不写入上下文。"""
    set_audit_trace(None)
    assert get_audit_trace() is None
    set_audit_trace("bad trace id!")
    assert get_audit_trace() is None


async def test_sanitize_masks_nonce_and_signature() -> None:
    """脱敏清单覆盖 nonce 与 signature。"""
    sanitized = sanitize_summary(
        {"nonce": "abc123", "signature": "sig456", "page": 2}
    )
    assert sanitized == {"nonce": "***", "signature": "***", "page": 2}


async def test_explicit_trace_id_overrides_context() -> None:
    """显式传入的 trace_id 优先于上下文。"""
    set_audit_trace("ctx-trace")
    db = MagicMock()
    AuditService(db).add_record(
        action="test.action",
        object_type="test",
        object_id="obj-1",
        trace_id="explicit-trace",
    )
    record = db.add.call_args.args[0]
    assert record.trace_id == "explicit-trace"
