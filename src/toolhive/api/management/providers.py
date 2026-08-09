"""管理面 Provider 管理 API。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_providers():
    """列出所有 Provider。"""
    return {"message": "stub"}


@router.post("")
async def create_provider():
    """注册新 Provider。"""
    return {"message": "stub"}


@router.get("/{provider_id}")
async def get_provider(provider_id: str):
    """获取 Provider 详情。"""
    return {"message": "stub"}


@router.post("/{provider_id}/health-check")
async def health_check(provider_id: str):
    """触发 Provider 健康检查。"""
    return {"message": "stub"}
