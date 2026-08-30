"""builtin 数学执行器测试。"""

from __future__ import annotations

import pytest

from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.runtime.errors import RUNTIME_PARAMETER_INVALID, RuntimeApiError
from toolhive.runtime.execution.gateway import BuiltinExecutor


def _binding(operation: str, mapping: dict | None = None) -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1",
        version_id="ver-1",
        provider_id="prov-1",
        method="COMPUTE",
        path_template=f"builtin://math/{operation}",
        parameter_mapping=mapping,
    )


def _provider() -> object:
    """builtin 执行器不依赖 Provider，传空对象即可。"""
    return object()


async def test_builtin_math_operations() -> None:
    """四则 / 幂 / 取模运算。"""
    executor = BuiltinExecutor()
    cases = [
        ("add", 1, 2, 3),
        ("subtract", 5, 2, 3),
        ("multiply", 3, 4, 12),
        ("divide", 9, 2, 4.5),
        ("power", 2, 10, 1024),
        ("modulo", 10, 3, 1),
    ]
    for operation, a, b, expected in cases:
        result = await executor.execute(
            _binding(operation), _provider(), {"a": a, "b": b},
        )
        assert result["result"] == expected


async def test_builtin_math_parameter_mapping() -> None:
    """参数映射按点分路径解析。"""
    executor = BuiltinExecutor()
    binding = _binding(
        "add",
        mapping={"a": "$.left.value", "b": "$.right"},
    )
    result = await executor.execute(
        binding, _provider(), {"left": {"value": 1}, "right": 2},
    )
    assert result["result"] == 3


async def test_builtin_math_operator_from_mapping() -> None:
    """operator 通过参数映射读取（$.operation）。"""
    executor = BuiltinExecutor()
    binding = _binding(
        "calculate",
        mapping={"a": "$.a", "b": "$.b", "operator": "$.operation"},
    )
    result = await executor.execute(
        binding, _provider(), {"a": 2, "b": 3, "operation": "power"},
    )
    assert result["result"] == 8


async def test_builtin_math_divide_by_zero() -> None:
    """除数为 0 返回参数错误。"""
    executor = BuiltinExecutor()
    with pytest.raises(RuntimeApiError) as exc_info:
        await executor.execute(_binding("divide"), _provider(), {"a": 1, "b": 0})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_builtin_math_unknown_operation() -> None:
    """未知操作返回 Provider 错误。"""
    executor = BuiltinExecutor()
    with pytest.raises(RuntimeApiError):
        await executor.execute(_binding("sqrt"), _provider(), {"a": 4, "b": 1})


async def test_builtin_math_rejects_non_numeric() -> None:
    """非数字参数被拒绝。"""
    executor = BuiltinExecutor()
    with pytest.raises(RuntimeApiError) as exc_info:
        await executor.execute(_binding("add"), _provider(), {"a": "x", "b": 1})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID
