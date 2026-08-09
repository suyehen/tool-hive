"""管理面认证 API：登录、登出、会话查询。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

router = APIRouter()


@router.post("/login")
async def login():
    """管理员登录，返回会话 Cookie。"""
    # TODO: 实现登录逻辑
    return {"message": "stub"}


@router.post("/logout")
async def logout():
    """管理员登出，撤销会话。"""
    return {"message": "stub"}


@router.get("/me")
async def current_user():
    """获取当前登录用户信息。"""
    return {"message": "stub"}
