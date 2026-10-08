"""Grant constraints 的持久化契约；请求时求值由 D9 实现。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from toolhive.core.domain.errors import InvalidDefinitionError


@dataclass(frozen=True)
class TimeWindow:
    timezone: ZoneInfo
    start: time
    end: time
    weekdays: frozenset[int]


@dataclass(frozen=True)
class GrantConstraints:
    ip_cidrs: tuple[IPv4Network | IPv6Network, ...] | None = None
    time_window: TimeWindow | None = None
    require_confirmation: bool = False


def parse_constraints(value: Mapping[str, Any]) -> GrantConstraints:
    if set(value) - {"ip_cidrs", "time_window", "require_confirmation"}:
        raise InvalidDefinitionError("授权约束包含未知或尚未支持的字段")
    networks = None
    if "ip_cidrs" in value:
        cidrs = value["ip_cidrs"]
        if not isinstance(cidrs, list) or not cidrs or not all(isinstance(x, str) for x in cidrs):
            raise InvalidDefinitionError("ip_cidrs 必须为非空 CIDR 列表")
        try:
            networks = tuple(ip_network(x, strict=False) for x in cidrs)
        except ValueError:
            raise InvalidDefinitionError("CIDR 无效") from None
    confirmation = value.get("require_confirmation", False)
    if not isinstance(confirmation, bool):
        raise InvalidDefinitionError("require_confirmation 必须为 boolean")
    window = None
    if "time_window" in value:
        raw = value["time_window"]
        if not isinstance(raw, dict) or set(raw) - {"timezone", "start", "end", "weekdays"}:
            raise InvalidDefinitionError("time_window 字段无效")
        try:
            zone = ZoneInfo(raw["timezone"])
            start = time.fromisoformat(raw["start"])
            end = time.fromisoformat(raw["end"])
        except (KeyError, TypeError, ValueError, ZoneInfoNotFoundError):
            raise InvalidDefinitionError("时间窗需有效 timezone 与 start/end") from None
        days = raw.get("weekdays", list(range(7)))
        if (
            not isinstance(days, list)
            or not days
            or any(
                isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6
                for day in days
            )
        ):
            raise InvalidDefinitionError("weekdays 必须为非空的 0..6 列表")
        if start.tzinfo is not None or end.tzinfo is not None or start == end:
            raise InvalidDefinitionError("start/end 应为不同的本地时间")
        window = TimeWindow(zone, start, end, frozenset(days))
    return GrantConstraints(networks, window, confirmation)
