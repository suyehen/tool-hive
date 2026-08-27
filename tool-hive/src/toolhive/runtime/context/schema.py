"""运行侧 ToolContext 契约与解析。"""

from __future__ import annotations

from dataclasses import dataclass

from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RuntimeApiError,
)

_CONTEXT_FIELDS = ("user_id", "tenant_id", "role", "channel", "session_id")
_MAX_FIELD_LENGTH = 128


@dataclass
class ToolContext:
    """调用系统声明的业务身份上下文（一期声明制）。"""

    user_id: str | None = None
    tenant_id: str | None = None
    role: str | None = None
    channel: str | None = None
    session_id: str | None = None

    def presence_summary(self) -> dict[str, bool]:
        """返回字段存在性摘要（不记录值，避免业务身份进入日志/Trace）。"""
        return {name: getattr(self, name) is not None for name in _CONTEXT_FIELDS}


def parse_tool_context(raw: object) -> ToolContext:
    """解析请求体顶层 ``context`` 对象；缺失返回全空上下文。"""
    if raw is None:
        return ToolContext()
    if not isinstance(raw, dict):
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID, "context 必须是 JSON 对象", 400,
        )
    unknown = set(raw) - set(_CONTEXT_FIELDS)
    if unknown:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID,
            f"context 包含未知字段: {', '.join(sorted(unknown))}",
            400,
        )
    values: dict[str, str | None] = {}
    for name in _CONTEXT_FIELDS:
        value = raw.get(name)
        if value is None:
            values[name] = None
            continue
        if not isinstance(value, str):
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"context.{name} 必须是字符串",
                400,
            )
        value = value.strip()
        if not value:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"context.{name} 不能为空字符串",
                400,
            )
        if len(value) > _MAX_FIELD_LENGTH:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"context.{name} 长度超过上限 {_MAX_FIELD_LENGTH}",
                400,
            )
        values[name] = value
    return ToolContext(**values)
