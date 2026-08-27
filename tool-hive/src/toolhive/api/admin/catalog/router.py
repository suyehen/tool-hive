"""Catalog 管理 API 聚合路由。"""

from __future__ import annotations

from fastapi import APIRouter

from toolhive.api.admin.catalog.capability_packs import (
    router as capability_packs_router,
)
from toolhive.api.admin.catalog.index_tasks import router as index_tasks_router
from toolhive.api.admin.catalog.providers import router as providers_router
from toolhive.api.admin.catalog.reviews import router as reviews_router
from toolhive.api.admin.catalog.tools import router as tools_router
from toolhive.api.admin.catalog.versions import router as versions_router

router = APIRouter(prefix="/catalog", tags=["Catalog"])
router.include_router(providers_router)
router.include_router(capability_packs_router)
router.include_router(tools_router)
router.include_router(versions_router)
router.include_router(reviews_router)
router.include_router(index_tasks_router)
