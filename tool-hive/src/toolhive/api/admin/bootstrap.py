"""管理侧初始化状态接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.deps import get_admin_security
from toolhive.config import AdminSecuritySettings
from toolhive.infrastructure.database import get_db
from toolhive.services.account_service import AccountService

router = APIRouter(prefix="/bootstrap", tags=["初始化"])


@router.get("/status")
async def get_bootstrap_status(
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
):
    """初始化状态：是否已存在管理账号。不泄露任何账号敏感信息。"""
    svc = AccountService(db, admin_security)
    initialized = await svc.has_any_account()
    return {"initialized": initialized}
