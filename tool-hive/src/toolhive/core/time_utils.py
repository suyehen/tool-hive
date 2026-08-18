"""统一时间工具与序列化类型。

接口时间输出格式统一为：
- 日期时间：``2026-08-18 08:30:00``（UTC）
- 日期：``2026-08-18``（UTC）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import PlainSerializer

_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
_DATE_FMT = "%Y-%m-%d"


def to_utc(dt: datetime) -> datetime:
    """统一转为 UTC；naive datetime 视为 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_datetime(dt: datetime | None) -> str | None:
    """格式化为 ``2026-08-18 08:30:00``（UTC）。"""
    if dt is None:
        return None
    return to_utc(dt).strftime(_DATETIME_FMT)


def format_date(dt: datetime | None) -> str | None:
    """格式化为 ``2026-08-18``（UTC 日期）。"""
    if dt is None:
        return None
    return to_utc(dt).strftime(_DATE_FMT)


UTCDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda v: format_datetime(v),
        return_type=str,
        when_used="json",
    ),
]

UTCDate = Annotated[
    datetime,
    PlainSerializer(
        lambda v: format_date(v),
        return_type=str,
        when_used="json",
    ),
]
