"""管理面工具 CRUD API。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def list_tools():
    """列出所有工具。"""
    return {"message": "stub"}


@router.post("")
async def create_tool():
    """创建新工具。"""
    return {"message": "stub"}


@router.get("/{tool_id}")
async def get_tool(tool_id: str):
    """获取单个工具详情（含版本列表）。"""
    return {"message": "stub"}


@router.put("/{tool_id}")
async def update_tool(tool_id: str):
    """更新工具元信息（不创建新版本）。"""
    return {"message": "stub"}


@router.get("/{tool_id}/versions")
async def list_versions(tool_id: str):
    """获取工具的所有版本。"""
    return {"message": "stub"}


@router.post("/{tool_id}/versions")
async def create_version(tool_id: str):
    """为工具创建新的不可变版本。"""
    return {"message": "stub"}


@router.put("/{tool_id}/versions/{version}")
async def update_version_status(tool_id: str, version: int):
    """变更版本状态（draft→active 等）。"""
    return {"message": "stub"}
