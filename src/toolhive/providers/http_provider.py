"""HttpToolProvider — 一期唯一 Provider 实现。"""

from __future__ import annotations

from typing import Any

import httpx

from toolhive.providers.base import BaseToolProvider


class HttpToolProvider(BaseToolProvider):
    """调用管理员预先审核的固定 HTTP API。

    LLM 只能传入业务参数；URL、Method、Header、凭据均来自 execution_config。
    """

    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def health_check(self) -> bool:
        # TODO: 实现健康检查
        return True

    async def execute(
        self,
        tool_id: str,
        version: int,
        arguments: dict[str, Any],
        execution_config: dict[str, Any],
    ) -> dict[str, Any]:
        # TODO: 实现固定 HTTP 调用
        raise NotImplementedError("HttpToolProvider.execute not implemented")
