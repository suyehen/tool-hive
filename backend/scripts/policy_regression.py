"""D 的离线契约回归；真实 Lua/数据库竞争由 policy_selfcheck 验证。"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.domain.errors import InvalidDefinitionError
from toolhive.core.domain.grant_constraints import parse_constraints
from toolhive.core.domain.models import (
    ExecutionBinding,
    Grant,
    Principal,
    Provider,
    Tool,
    ToolChannel,
    ToolVersion,
)
from toolhive.core.policy.authorization import AuthorizationService
from toolhive.core.policy.confirmation import confirmation_required
from toolhive.core.policy.constraints import constraints_allow
from toolhive.core.policy.contracts import RequestContext
from toolhive.core.policy.degradation import (
    FAILURE_MODES,
    FailureMode,
    Mechanism,
    dependency_failed,
)
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.idempotency import request_fingerprint
from toolhive.core.policy.store import PolicyStore


def run() -> None:
    monday_night = parse_constraints(
        {
            "ip_cidrs": ["10.0.0.0/8", "2001:db8::/32"],
            "time_window": {"timezone": "UTC", "start": "22:00", "end": "02:00", "weekdays": [0]},
        }
    )
    assert constraints_allow(
        monday_night, RequestContext(datetime(2026, 10, 6, 1, tzinfo=UTC), "10.1.2.3")
    )
    assert not constraints_allow(
        monday_night, RequestContext(datetime(2026, 10, 6, 2, tzinfo=UTC), "10.1.2.3")
    )
    assert not constraints_allow(
        monday_night, RequestContext(datetime(2026, 10, 5, 23, tzinfo=UTC))
    )
    assert not constraints_allow(
        monday_night, RequestContext(datetime(2026, 10, 5, 23, tzinfo=UTC), "invalid")
    )
    malformed: dict[str, Any]
    for malformed in (
        {"time_window": {}},
        {"ip_cidrs": []},
        {"require_confirmation": 1},
        {"unknown": True},
    ):
        try:
            parse_constraints(malformed)
        except InvalidDefinitionError:
            pass
        else:
            raise AssertionError("malformed constraints accepted")
    print(
        "[PASS] constraints: CIDR, missing IP, overnight weekdays, exclusive "
        "end, invalid definitions"
    )
    version = ToolVersion(side_effect="read", risk="low")
    assert not confirmation_required(version)
    for side_effect, risk in (("write", "low"), ("unknown", "low"), ("read", "high")):
        version.side_effect, version.risk = side_effect, risk
        assert confirmation_required(version)
    print("[PASS] confirmation: read/write/unknown and high risk")
    fp = request_fingerprint(2**60, None, {"b": 2, "a": 1})
    assert fp == request_fingerprint(2**60, "stable", {"a": 1, "b": 2}, {"trace_id": "different"})
    assert fp != request_fingerprint(2**60, "beta", {"a": 1, "b": 2})
    assert fp != request_fingerprint(2**60, "stable", {"a": 2, "b": 2})
    assert request_fingerprint(
        1, None, {}, {"locale": "en"}, context_fields=frozenset({"locale"})
    ) != request_fingerprint(1, None, {}, {"locale": "zh"}, context_fields=frozenset({"locale"}))
    assert FAILURE_MODES[Mechanism.IDEMPOTENCY] == FailureMode.CLOSED
    assert FAILURE_MODES[Mechanism.DATABASE] == FailureMode.CLOSED
    assert FAILURE_MODES[Mechanism.VISIBILITY] == FailureMode.BYPASS
    assert all(
        FAILURE_MODES[m] == FailureMode.OPEN
        for m in (Mechanism.QPS, Mechanism.DAILY, Mechanism.CONCURRENCY, Mechanism.CIRCUIT)
    )
    print(
        "[PASS] fingerprint: canonical args, selector normalization, context "
        "whitelist; failure matrix"
    )


async def authorization_regression() -> None:
    failures = (
        None,
        "principal",
        "tool",
        "stable",
        "version",
        "executable",
        "binding",
        "provider",
        "grant",
    )
    for failure in failures:
        principal = Principal(id=1, status="enabled")
        tool = Tool(id=2, status="enabled")
        stable = ToolChannel(tool_id=2, name="stable", version_id=3)
        version = ToolVersion(
            id=3, tool_id=2, status="published", executable=True, domain="demo", tags=[]
        )
        binding = ExecutionBinding(provider_id=4, version_id=3)
        provider = Provider(id=4, status="enabled")
        grants = [
            Grant(
                id=5,
                principal_id=1,
                status="active",
                scope_type="domain",
                scope_value="demo",
                quota={},
                constraints={},
            )
        ]
        if failure == "principal":
            principal.status = "disabled"
        if failure == "tool":
            tool.status = "disabled"
        if failure == "version":
            version.status = "draft"
        if failure == "executable":
            version.executable = False
        if failure == "provider":
            provider.status = "disabled"
        session = MagicMock(spec=AsyncSession)
        session.scalar = AsyncMock(
            side_effect=[
                principal,
                tool,
                None if failure == "stable" else stable,
                version,
                stable,
                version,
                None if failure == "binding" else binding,
                provider,
            ]
        )
        result = MagicMock()
        result.all.return_value = [] if failure == "grant" else grants
        session.scalars = AsyncMock(return_value=result)
        service = AuthorizationService(session, PolicyStore(MagicMock(spec=Redis)))
        try:
            auth = await service.resolve(1, "demo.query")
            assert failure is None and auth.version.id == 3
        except PolicyError as exc:
            assert failure is not None and exc.code == "TH_TOOL_NOT_FOUND"
            assert exc.message == "工具不可用"
    with patch("toolhive.core.policy.degradation._log") as logger:
        for mechanism, mode in FAILURE_MODES.items():
            try:
                actual = dependency_failed(mechanism)
                assert mode != FailureMode.CLOSED and actual == mode
            except PolicyError as exc:
                assert mode == FailureMode.CLOSED and exc.code == "TH_DEPENDENCY_UNAVAILABLE"
        assert logger.error.call_count == len(FAILURE_MODES)
        assert all("exc_info" not in call.kwargs for call in logger.error.call_args_list)
    print("[PASS] unavailable authorization states; every failure-matrix cell and alert")


if __name__ == "__main__":
    run()
    asyncio.run(authorization_regression())
