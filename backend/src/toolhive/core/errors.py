"""协议无关的错误语义（设计 §7.4）；HTTP/MCP 映射属于协议适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorDefinition:
    message: str
    retryable: bool


ERRORS = {
    "TH_AUTH_INVALID": ErrorDefinition("认证失败", False),
    "TH_AUTH_FORBIDDEN": ErrorDefinition("不允许从当前来源访问", False),
    "TH_PARAMETER_INVALID": ErrorDefinition("请求参数无效", False),
    "TH_TOOL_NOT_FOUND": ErrorDefinition("工具不可用", False),
    "TH_CONFIRMATION_REQUIRED": ErrorDefinition("该工具需要确认", False),
    "TH_CONFIRMATION_INVALID": ErrorDefinition("确认令牌无效", False),
    "TH_IDEMPOTENCY_IN_PROGRESS": ErrorDefinition("重复请求处理中，请稍后重试", True),
    "TH_EXECUTION_OUTCOME_UNKNOWN": ErrorDefinition("执行结果待确认，请查询原执行状态", False),
    "TH_IDEMPOTENCY_KEY_REUSED": ErrorDefinition("幂等键已用于其他请求，请更换 key", False),
    "TH_RATE_LIMITED": ErrorDefinition("请求过于频繁", True),
    "TH_CONCURRENCY_LIMITED": ErrorDefinition("并发超限", True),
    "TH_QUOTA_EXCEEDED": ErrorDefinition("已达调用配额", False),
    "TH_CIRCUIT_OPEN": ErrorDefinition("目标服务暂时不可用", True),
    "TH_DEADLINE_EXCEEDED": ErrorDefinition("请求处理超时", True),
    "TH_UPSTREAM_TIMEOUT": ErrorDefinition("目标服务响应超时", True),
    "TH_UPSTREAM_ERROR": ErrorDefinition("目标服务调用失败", True),
    "TH_UPSTREAM_REJECTED": ErrorDefinition("目标服务拒绝了请求", False),
    "TH_CHANNEL_REFERENCES_VERSION": ErrorDefinition("该版本仍被引用", False),
    "TH_RETRIEVAL_UNAVAILABLE": ErrorDefinition("检索服务暂时不可用", True),
    "TH_DEPENDENCY_UNAVAILABLE": ErrorDefinition("服务依赖不可用，请求被拒绝", True),
    "TH_INTERNAL_ERROR": ErrorDefinition("内部错误", True),
}


class ToolHiveError(Exception):
    """稳定错误码；不保存依赖异常、敏感参数或协议状态码。"""

    def __init__(self, code: str, *, retry_after_ms: int | None = None) -> None:
        definition = ERRORS[code]
        self.code = code
        self.message = definition.message
        self.retryable = definition.retryable
        self.retry_after_ms = retry_after_ms
        super().__init__(self.message)

    def as_dict(self, trace_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "trace_id": trace_id,
        }
        if self.retry_after_ms is not None:
            body["retry_after_ms"] = self.retry_after_ms
        return body
