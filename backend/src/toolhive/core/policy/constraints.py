"""D9：当前请求的 IP 与时间窗求值，不加入可见集合缓存。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from ipaddress import ip_address

from toolhive.core.domain.grant_constraints import GrantConstraints
from toolhive.core.policy.contracts import GrantPolicy, RequestContext
from toolhive.core.policy.errors import PolicyError


def constraints_allow(constraints: GrantConstraints, context: RequestContext) -> bool:
    if context.now.tzinfo is None:
        raise ValueError("请求时刻必须带时区")
    if constraints.ip_cidrs is not None:
        try:
            address = ip_address(context.source_ip or "")
        except ValueError:
            return False
        if not any(address in network for network in constraints.ip_cidrs):
            return False
    window = constraints.time_window
    if window is not None:
        local = context.now.astimezone(window.timezone)
        current = local.time().replace(tzinfo=None)
        day = local.weekday()
        if window.start < window.end:
            allowed = window.start <= current < window.end
        else:
            allowed = current >= window.start or current < window.end
            if current < window.end:
                day = (local - timedelta(days=1)).weekday()
        if not allowed or day not in window.weekdays:
            return False
    return True


def enforce_constraints(grants: Iterable[GrantPolicy], context: RequestContext) -> None:
    if not all(constraints_allow(grant.constraints, context) for grant in grants):
        raise PolicyError("TH_AUTH_FORBIDDEN")
