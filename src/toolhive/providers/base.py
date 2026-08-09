"""Provider 抽象基类。所有 Provider 必须实现统一接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseToolProvider(ABC):
    """Provider 统一契约：sync、get_definition、health_check、execute。"""

    @abstractmethod
    async def health_check(self) -> bool:
        """检查 Provider 是否可达。"""
        ...

    @abstractmethod
    async def execute(
        self,
        tool_id: str,
        version: int,
        arguments: dict[str, Any],
        execution_config: dict[str, Any],
    ) -> dict[str, Any]:
        """执行工具调用，返回标准化结果。"""
        ...
