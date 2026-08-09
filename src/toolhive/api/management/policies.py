"""管理面策略管理 API。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/bindings")
async def list_policy_bindings():
    """列出所有策略绑定。"""
    return {"message": "stub"}


@router.post("/bindings")
async def create_policy_binding():
    """创建策略绑定。"""
    return {"message": "stub"}


@router.get("/capabilities")
async def list_capabilities():
    """列出所有 Capability。"""
    return {"message": "stub"}


@router.get("/bundles")
async def list_entitlement_bundles():
    """列出所有权限包。"""
    return {"message": "stub"}
