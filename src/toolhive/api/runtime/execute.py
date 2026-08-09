"""运行面 Execute API — 工具执行。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def execute():
    """执行指定的工具调用，完成 ToolPolicy.Execute → Schema 校验 → Provider 路由。"""
    # TODO: 实现 ExecuteService
    return {"message": "stub"}
