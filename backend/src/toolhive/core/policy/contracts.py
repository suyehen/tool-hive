"""策略层不可变输入快照，不引用协议或请求框架。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from toolhive.core.domain.grant_constraints import GrantConstraints, parse_constraints
from toolhive.core.domain.models import ExecutionBinding, Grant, Provider, Tool, ToolVersion


@dataclass(frozen=True)
class RequestContext:
    now: datetime
    source_ip: str | None = None


@dataclass(frozen=True)
class GrantPolicy:
    id: int
    principal_id: int
    scope_type: str
    scope_value: str
    qps: int | None
    daily: int | None
    concurrency: int | None
    constraints: GrantConstraints

    @classmethod
    def from_model(cls, grant: Grant) -> GrantPolicy:
        quota: dict[str, Any] = grant.quota
        from toolhive.core.domain.errors import InvalidDefinitionError

        if set(quota) - {"qps", "daily", "concurrency"} or any(
            isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in quota.values()
        ):
            raise InvalidDefinitionError("配额定义无效")
        return cls(
            grant.id,
            grant.principal_id,
            grant.scope_type,
            grant.scope_value,
            quota.get("qps"),
            quota.get("daily"),
            quota.get("concurrency"),
            parse_constraints(grant.constraints),
        )


@dataclass(frozen=True)
class Authorization:
    principal_id: int
    tool: Tool
    version: ToolVersion
    binding: ExecutionBinding
    provider: Provider
    grants: tuple[GrantPolicy, ...]


def normalize_selector(selector: str | None) -> str:
    if selector is None or selector in {"stable", "beta", "canary"}:
        return "channel:" + (selector or "stable")
    if selector.startswith(("channel:", "version:")):
        return selector
    return "version:" + selector
