"""运行面路由 — 内网 Resolve / Execute。"""

from __future__ import annotations

from fastapi import APIRouter

from toolhive.api.runtime.resolve import router as resolve_router
from toolhive.api.runtime.execute import router as execute_router

runtime_router = APIRouter()

runtime_router.include_router(resolve_router, prefix="/resolve", tags=["工具发现"])
runtime_router.include_router(execute_router, prefix="/execute", tags=["工具执行"])
