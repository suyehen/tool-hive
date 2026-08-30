"""统一 ProviderGateway：所有业务出站必经（一期 builtin，http 阶段 5 接入）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_ERROR,
    RuntimeApiError,
)


class ProviderExecutor(ABC):
    """Provider 执行器接口：按固定绑定执行并返回标准化 JSON 结果。"""

    provider_type: str

    @abstractmethod
    async def execute(
        self,
        binding: CatalogExecutionBinding,
        provider: CatalogProvider,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """执行绑定并返回 JSON 结果。"""


def _resolve_argument(arguments: dict[str, Any], key: str) -> Any:
    """按点分路径解析参数（如 ``a.b``）。"""
    current: Any = arguments
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"缺少参数: {key}",
                400,
            )
        current = current[part]
    return current


def _map_value(spec: Any, arguments: dict[str, Any]) -> Any:
    """映射值：``$.path`` 引用参数，其余为固定常量。"""
    if isinstance(spec, str) and spec.startswith("$."):
        return _resolve_argument(arguments, spec[2:])
    return spec


class BuiltinExecutor(ProviderExecutor):
    """平台内置执行器（一期：数学计算）。"""

    provider_type = "builtin"

    async def execute(
        self,
        binding: CatalogExecutionBinding,
        provider: CatalogProvider,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """按 ``builtin://math/{operation}`` 路径执行数学计算。"""
        path = binding.path_template or ""
        if not path.startswith("builtin://math/"):
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                f"不支持的内置操作: {path}",
                400,
            )
        operation = path.rsplit("/", 1)[-1]
        mapping = binding.parameter_mapping or {}
        operator_spec = mapping.get("operator")
        if operator_spec is not None:
            operation = str(_map_value(operator_spec, arguments))
        left_spec = mapping.get("a", "$.a")
        right_spec = mapping.get("b", "$.b")
        a = _map_value(left_spec, arguments)
        b = _map_value(right_spec, arguments)
        if isinstance(a, bool) or not isinstance(a, (int, float)):
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID, "参数 a 必须是数字", 400,
            )
        if isinstance(b, bool) or not isinstance(b, (int, float)):
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID, "参数 b 必须是数字", 400,
            )
        result = self._compute(operation, a, b)
        return {"result": result}

    @staticmethod
    def _compute(operation: str, a: int | float, b: int | float) -> int | float:
        """执行四则 / 幂 / 取模运算。"""
        if operation == "add":
            return a + b
        if operation == "subtract":
            return a - b
        if operation == "multiply":
            return a * b
        if operation == "divide":
            if b == 0:
                raise RuntimeApiError(
                    RUNTIME_PARAMETER_INVALID, "除数不能为 0", 400,
                )
            return a / b
        if operation == "power":
            return a ** b
        if operation == "modulo":
            if b == 0:
                raise RuntimeApiError(
                    RUNTIME_PARAMETER_INVALID, "模数不能为 0", 400,
                )
            return a % b
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, f"未知数学操作: {operation}", 400,
        )

class ProviderGateway:
    """统一出站网关：按 Provider 类型分发到固定执行器。"""

    def __init__(self, executors: dict[str, ProviderExecutor] | None = None):
        self._executors = executors or {}

    async def execute(
        self,
        binding: CatalogExecutionBinding,
        provider: CatalogProvider,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """执行绑定；未注册类型默认拒绝。"""
        provider_type = getattr(provider, "provider_type", "")
        executor = self._executors.get(provider_type)
        if executor is None:
            raise RuntimeApiError(
                RUNTIME_PROVIDER_ERROR,
                f"未注册的 Provider 类型: {provider_type}",
                503,
            )
        return await executor.execute(binding, provider, arguments)
