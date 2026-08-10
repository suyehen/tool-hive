"""ToolHive 应用入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from toolhive.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    yield
    # 关闭时清理资源
    from toolhive.infrastructure.redis import close_redis
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# 挂载管理侧子应用：/api/admin/**
from toolhive.api.admin.router import admin_app  # noqa: E402

app.mount("/api/admin", admin_app)


@app.get("/health")
async def health():
    return {"status": "ok"}
