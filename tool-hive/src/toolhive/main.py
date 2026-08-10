"""ToolHive 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from toolhive.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)


@app.get("/health")
async def health():
    return {"status": "ok"}
