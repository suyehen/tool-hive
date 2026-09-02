"""调用系统 IP 规则管理 API 测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from toolhive.api.admin.caller_systems.router import update_ip_rule_status
from toolhive.api.admin.caller_systems.schemas import IPRuleStatusUpdateRequest
from toolhive.core.enums import IPRuleStatus


async def test_ip_rule_status_update_uses_explicit_target_state() -> None:
    """IP 规则状态切换按显式目标状态执行，支持禁用后重新启用。"""
    with patch(
        "toolhive.api.admin.caller_systems.router.CallerSystemService"
    ) as svc_cls:
        svc = svc_cls.return_value
        svc.update_ip_rule_status = AsyncMock()
        await update_ip_rule_status(
            "rule-1",
            IPRuleStatusUpdateRequest(enabled=True),
            db=AsyncMock(),
            _account=object(),
        )
        svc.update_ip_rule_status.assert_awaited_once_with(
            "rule-1", IPRuleStatus.ACTIVE,
        )

        await update_ip_rule_status(
            "rule-1",
            IPRuleStatusUpdateRequest(enabled=False),
            db=AsyncMock(),
            _account=object(),
        )
        svc.update_ip_rule_status.assert_awaited_with("rule-1", IPRuleStatus.DISABLED)
