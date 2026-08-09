"""管理面路由 — tools.xuan2.com 公网入口。"""

from __future__ import annotations

from fastapi import APIRouter

from toolhive.api.management.auth import router as auth_router
from toolhive.api.management.tools import router as tools_router
from toolhive.api.management.providers import router as providers_router
from toolhive.api.management.policies import router as policies_router

management_router = APIRouter()

management_router.include_router(auth_router, prefix="/auth", tags=["认证"])
management_router.include_router(tools_router, prefix="/tools", tags=["工具管理"])
management_router.include_router(providers_router, prefix="/providers", tags=["Provider"])
management_router.include_router(policies_router, prefix="/policies", tags=["策略"])
