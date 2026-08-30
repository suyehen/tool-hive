"""轻量 JSON Schema 校验器（一期内置，不引入第三方依赖）。"""

from __future__ import annotations

import re
from typing import Any

from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RuntimeApiError,
)


class JsonSchemaValidator:
    """支持 type/required/properties/长度/数值边界/数组/禁止未知属性的轻量校验。"""

    def __init__(self, schema: dict[str, Any] | None):
        self.schema = schema

    def validate(self, value: Any, *, path: str = "arguments") -> None:
        """按 Schema 校验参数；非法时抛 RUNTIME_PARAMETER_INVALID。"""
        if self.schema is None:
            return
        self._validate_value(value, self.schema, path)

    def _fail(self, path: str, detail: str) -> None:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID, f"{path}: {detail}", 400,
        )

    def _validate_value(
        self, value: Any, schema: dict[str, Any], path: str,
    ) -> None:
        schema_type = schema.get("type", "object")
        if schema_type == "object":
            self._validate_object(value, schema, path)
        elif schema_type == "string":
            self._validate_string(value, schema, path)
        elif schema_type == "number":
            self._validate_number(value, schema, path)
        elif schema_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                self._fail(path, "必须是整数")
            self._validate_number(value, schema, path)
        elif schema_type == "boolean":
            if not isinstance(value, bool):
                self._fail(path, "必须是布尔值")
        elif schema_type == "array":
            self._validate_array(value, schema, path)
        elif schema_type == "null":
            if value is not None:
                self._fail(path, "必须为 null")
        # 未知 type 宽松跳过，避免误伤自定义扩展

    def _validate_object(
        self, value: Any, schema: dict[str, Any], path: str,
    ) -> None:
        if not isinstance(value, dict):
            self._fail(path, "必须是 JSON 对象")
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                self._fail(path, f"缺少必填字段 {name}")
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name not in properties:
                if additional is False:
                    self._fail(path, f"不允许的字段: {name}")
                continue
            self._validate_value(item, properties[name], f"{path}.{name}")

    def _validate_string(
        self, value: Any, schema: dict[str, Any], path: str,
    ) -> None:
        if not isinstance(value, str):
            self._fail(path, "必须是字符串")
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(value) < min_length:
            self._fail(path, f"长度不能小于 {min_length}")
        if max_length is not None and len(value) > max_length:
            self._fail(path, f"长度不能超过 {max_length}")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            self._fail(path, "不匹配允许的格式")
        enum = schema.get("enum")
        if enum is not None and value not in enum:
            self._fail(path, "不在允许的取值范围内")

    def _validate_number(
        self, value: Any, schema: dict[str, Any], path: str,
    ) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._fail(path, "必须是数字")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            self._fail(path, f"不能小于 {minimum}")
        if maximum is not None and value > maximum:
            self._fail(path, f"不能大于 {maximum}")

    def _validate_array(
        self, value: Any, schema: dict[str, Any], path: str,
    ) -> None:
        if not isinstance(value, list):
            self._fail(path, "必须是数组")
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < min_items:
            self._fail(path, f"至少 {min_items} 项")
        if max_items is not None and len(value) > max_items:
            self._fail(path, f"最多 {max_items} 项")
        items_schema = schema.get("items")
        if items_schema:
            for index, item in enumerate(value):
                self._validate_value(item, items_schema, f"{path}[{index}]")
