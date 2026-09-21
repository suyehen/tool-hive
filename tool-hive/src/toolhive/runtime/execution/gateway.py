"""统一 ProviderGateway：所有业务出站必经（一期 builtin，http 阶段 5 接入）。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any

from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_ERROR,
    RuntimeApiError,
)

# 运算规模上限：内置执行器在事件循环内同步计算，必须限制可被放大的输入，
# 否则单次调用即可长时间占满 worker（幂运算尤其容易构造）。
MAX_OPERAND_ABS = 1e15
"""单个操作数的绝对值上限。"""

MAX_POWER_EXPONENT = 10000
"""幂运算指数绝对值上限（结果位数上限会先一步拦截更大的结果）。"""

MAX_RESULT_BITS = 8192
"""整数结果二进制位数上限（约 2466 位十进制，确保可 JSON 序列化）。"""


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
        _check_operand(a, "a")
        _check_operand(b, "b")
        result = self._compute(operation, a, b)
        return {"result": result}

    @staticmethod
    def _compute(operation: str, a: int | float, b: int | float) -> int | float:
        """执行四则 / 幂 / 取模运算，并限制结果规模。"""
        try:
            result = BuiltinExecutor._compute_raw(operation, a, b)
        except OverflowError as exc:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID, "计算结果超出可表示范围", 400,
            ) from exc
        _check_result(result)
        return result

    @staticmethod
    def _compute_raw(operation: str, a: int | float, b: int | float) -> int | float:
        """执行四则 / 幂 / 取模运算（调用前必须已完成入参范围校验）。"""
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
            return _power(a, b)
        if operation == "modulo":
            if b == 0:
                raise RuntimeApiError(
                    RUNTIME_PARAMETER_INVALID, "模数不能为 0", 400,
                )
            return a % b
        raise RuntimeApiError(
            RUNTIME_PROVIDER_ERROR, f"未知数学操作: {operation}", 400,
        )


def _check_operand(value: int | float, name: str) -> None:
    """校验单个操作数：必须是有限数且不超过量级上限。"""
    if isinstance(value, float) and not math.isfinite(value):
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID, f"参数 {name} 必须是有限数字", 400,
        )
    if abs(value) > MAX_OPERAND_ABS:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID,
            f"参数 {name} 的绝对值不能超过 {MAX_OPERAND_ABS:g}",
            400,
        )


def _check_result(result: int | float) -> None:
    """校验计算结果规模，防止超大整数进入响应与 Trace 序列化。"""
    if isinstance(result, float):
        if not math.isfinite(result):
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID, "计算结果超出可表示范围", 400,
            )
        return
    if isinstance(result, int) and result.bit_length() > MAX_RESULT_BITS:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID,
            f"计算结果位数超过上限 {MAX_RESULT_BITS} 位",
            400,
        )


def _power(a: int | float, b: int | float) -> int | float:
    """幂运算：先按估算规模拒绝，避免在事件循环内做无界计算。"""
    if abs(b) > MAX_POWER_EXPONENT:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID,
            f"幂运算指数绝对值不能超过 {MAX_POWER_EXPONENT}",
            400,
        )
    if isinstance(a, int) and isinstance(b, int) and b > 0:
        # 提前估算结果位数（|a|^b 的位长约 b * (bit_length(a) - 1) + 1），
        # 超限时直接拒绝，不进入实际计算；估算偏小也无妨，_check_result 会兜底
        estimated_bits = b * (a.bit_length() - 1) + 1
        if estimated_bits > MAX_RESULT_BITS:
            raise RuntimeApiError(
                RUNTIME_PARAMETER_INVALID,
                f"幂运算结果位数超过上限 {MAX_RESULT_BITS} 位",
                400,
            )
    return a ** b

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
