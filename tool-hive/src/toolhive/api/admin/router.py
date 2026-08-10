"""管理侧子应用。挂载 Session/CSRF 中间件并注册所有子路由。"""

from __future__ import annotations

from fastapi import FastAPI

from toolhive.api.admin.auth.router import router as auth_router
from toolhive.api.admin.accounts.router import router as accounts_router
from toolhive.api.admin.roles.router import (
    _ops_router as operations_router,
    router as roles_router,
)
from toolhive.api.admin.caller_systems.router import router as caller_systems_router
from toolhive.api.admin.middleware import CSRFMiddleware, SessionMiddleware

admin_app = FastAPI(
    title="ToolHive Admin API",
    version="0.1.0",
)

# 中间件按添加顺序逆序执行：SessionMiddleware 先执行 → CSRFMiddleware
admin_app.add_middleware(CSRFMiddleware)
admin_app.add_middleware(SessionMiddleware)

# 注册子路由
admin_app.include_router(auth_router)
admin_app.include_router(accounts_router)
admin_app.include_router(roles_router)
admin_app.include_router(operations_router)
admin_app.include_router(caller_systems_router)
