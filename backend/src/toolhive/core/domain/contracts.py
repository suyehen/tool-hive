"""领域写入契约与校验；不进行请求授权或出站。"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from toolhive.core.domain.errors import InvalidDefinitionError

IdFactory = Callable[[], int]
DEFINITION_FIELDS = (
    "name",
    "description",
    "domain",
    "system",
    "tags",
    "risk",
    "side_effect",
    "retry_safe",
    "executable",
    "discoverable",
    "input_schema",
    "output_schema",
)
BINDING_FIELDS = (
    "provider_id",
    "method",
    "path_template",
    "param_mapping",
    "timeout_seconds",
    "retry_max",
)


@dataclass(frozen=True)
class Actor:
    """已由管理入口确认的操作者，用于审计；不是授权凭证。"""

    id: int | None
    name: str | None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    input_schema: dict[str, Any]
    description: str | None = None
    domain: str | None = None
    system: str | None = None
    tags: tuple[str, ...] = ()
    risk: Literal["low", "medium", "high"] = "low"
    side_effect: Literal["read", "write", "unknown"] = "unknown"
    retry_safe: bool = False
    discoverable: bool = True
    output_schema: dict[str, Any] | None = None

    @property
    def executable(self) -> bool:
        """M0 的能力标记，未知副作用与需确认工具均拒绝执行。"""
        return self.side_effect == "read" and self.risk != "high"

    def validate(self) -> None:
        if not self.name.strip() or len(self.name) > 200:
            raise InvalidDefinitionError("工具名称为空或过长")
        if self.risk not in {"low", "medium", "high"}:
            raise InvalidDefinitionError("风险等级无效")
        if self.side_effect not in {"read", "write", "unknown"}:
            raise InvalidDefinitionError("副作用声明无效")
        if self.retry_safe and self.side_effect == "unknown":
            raise InvalidDefinitionError("未知副作用不能声明重试安全")
        for schema in (self.input_schema, self.output_schema):
            if schema is None:
                continue
            if not isinstance(schema, dict):
                raise InvalidDefinitionError("schema 必须为 JSON 对象")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise InvalidDefinitionError("schema 定义无效") from None
        if self.input_schema is None:
            raise InvalidDefinitionError("input_schema 必需")


@dataclass(frozen=True)
class BindingDefinition:
    provider_id: int
    method: str | None = None
    path_template: str | None = None
    param_mapping: dict[str, Any] | None = None
    timeout_seconds: int | None = None
    retry_max: int | None = None

    def validate(self, provider_type: str) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise InvalidDefinitionError("绑定超时必须为正数")
        if self.retry_max is not None and self.retry_max < 0:
            raise InvalidDefinitionError("绑定重试次数不能为负数")
        if provider_type == "http":
            if self.method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
                raise InvalidDefinitionError("HTTP 方法无效")
            if not self.path_template or not self.path_template.startswith("/"):
                raise InvalidDefinitionError("HTTP 路径模板必需且为相对路径")
            if self.path_template.startswith("//") or not isinstance(self.param_mapping, dict):
                raise InvalidDefinitionError("HTTP 参数映射必需且路径不能覆盖主机")
            if re.search(r"\{[^{}]+\}", self.path_template) and not self.param_mapping:
                raise InvalidDefinitionError("路径占位符需要参数映射")
        elif provider_type == "local":
            if self.method != "COMPUTE" or self.path_template is not None:
                raise InvalidDefinitionError("local 绑定只允许 COMPUTE")
            if self.param_mapping is not None:
                raise InvalidDefinitionError("local 绑定不使用 HTTP 参数映射")
        else:
            raise InvalidDefinitionError("M0 不支持该 Provider 类型")
