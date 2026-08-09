"""运行面 Resolve API — 工具发现与召回。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("")
async def resolve():
    """根据用户意图检索可用工具，返回经 ToolPolicy.Discover 过滤的候选列表。"""
    # TODO: 实现 ResolveService
    return {"message": "stub"}
