"""FastAPI 应用入口 — 管理面 + 运行面双端口启动。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from toolhive.api.management.router import management_router
from toolhive.api.runtime.router import runtime_router
from toolhive.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库连接池，关闭时释放。"""
    # TODO: 初始化数据库引擎 & Chroma 客户端
    yield
    # TODO: 关闭数据库引擎


def create_management_app() -> FastAPI:
    """创建管理面应用（公网 `tools.xuan2.com`）。"""
    app = FastAPI(
        title=f"{settings.app_name} Management API",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.include_router(management_router, prefix="/api/v1")
    return app


def create_runtime_app() -> FastAPI:
    """创建运行面应用（内网，仅服务间调用）。"""
    app = FastAPI(
        title=f"{settings.app_name} Runtime API",
        version=settings.app_version,
    )
    app.include_router(runtime_router, prefix="/api/v1")
    return app


management_app = create_management_app()
runtime_app = create_runtime_app()
