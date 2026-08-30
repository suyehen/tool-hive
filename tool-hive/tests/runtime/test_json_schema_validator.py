"""轻量 JSON Schema 校验器测试。"""

from __future__ import annotations

import pytest

from toolhive.runtime.errors import RUNTIME_PARAMETER_INVALID, RuntimeApiError
from toolhive.runtime.validation.json_schema import JsonSchemaValidator


def _validate(schema: dict, value) -> None:
    JsonSchemaValidator(schema).validate(value)


async def test_validator_none_schema_skips() -> None:
    """未配置 Schema 时跳过校验。"""
    _validate(None, {"a": 1})


async def test_validator_required_and_type() -> None:
    """必填字段与类型校验。"""
    schema = {
        "type": "object",
        "required": ["a", "b"],
        "properties": {
            "a": {"type": "number", "minimum": 0},
            "b": {"type": "number"},
            "operator": {"type": "string", "maxLength": 8},
        },
    }
    _validate(schema, {"a": 1, "b": 2})
    with pytest.raises(RuntimeApiError) as exc_info:
        _validate(schema, {"a": 1})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID
    with pytest.raises(RuntimeApiError):
        _validate(schema, {"a": -1, "b": 2})
    with pytest.raises(RuntimeApiError):
        _validate(schema, {"a": "x", "b": 2})


async def test_validator_rejects_unknown_properties() -> None:
    """additionalProperties=false 时拒绝未知字段。"""
    schema = {
        "type": "object",
        "properties": {"a": {"type": "number"}},
        "additionalProperties": False,
    }
    with pytest.raises(RuntimeApiError) as exc_info:
        _validate(schema, {"a": 1, "evil": 2})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_validator_string_limits() -> None:
    """字符串长度限制。"""
    schema = {"type": "string", "minLength": 2, "maxLength": 4}
    _validate(schema, "ab")
    with pytest.raises(RuntimeApiError):
        _validate(schema, "a")
    with pytest.raises(RuntimeApiError):
        _validate(schema, "abcde")


async def test_validator_array_items() -> None:
    """数组类型与元素校验。"""
    schema = {
        "type": "array",
        "items": {"type": "integer"},
        "maxItems": 2,
    }
    _validate(schema, [1, 2])
    with pytest.raises(RuntimeApiError):
        _validate(schema, [1, "x"])
    with pytest.raises(RuntimeApiError):
        _validate(schema, [1, 2, 3])


async def test_validator_boolean_and_null() -> None:
    """布尔与 null 类型。"""
    _validate({"type": "boolean"}, True)
    _validate({"type": "null"}, None)
    with pytest.raises(RuntimeApiError):
        _validate({"type": "boolean"}, 1)


async def test_validator_enum() -> None:
    """enum 取值限制。"""
    schema = {"type": "string", "enum": ["add", "subtract"]}
    _validate(schema, "add")
    with pytest.raises(RuntimeApiError):
        _validate(schema, "sqrt")
