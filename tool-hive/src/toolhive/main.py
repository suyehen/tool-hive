"""ToolHive 应用入口。"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI

# 启动阶段统一加载配置：--config 或 TOOLHIVE_CONFIG_FILE 指定外挂 YAML
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--config", dest="config_file", default=None)
_args, _ = _parser.parse_known_args()

# 延迟导入：需先解析 --config 再加载配置
from toolhive.config import load_settings  # noqa: E402

settings = load_settings(_args.config_file)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 生产配置校验：不满足时启动失败并输出明确原因
    from toolhive.config import validate_production_settings
    validate_production_settings(settings)

    # 启动阶段：初始化基础设施与管理安全配置分区
    from toolhive.infrastructure.database import init_infrastructure
    from toolhive.infrastructure.redis import init_redis

    init_infrastructure(settings.infrastructure, debug=settings.debug)
    init_redis(settings.infrastructure)

    from toolhive.core import snowflake
    from toolhive.services.security import (
        captcha,
        csrf,
        password,
        rate_limit,
    )
    from toolhive.services.security import (
        session as session_security,
    )
    admin_security = settings.admin_security
    snowflake.configure_snowflake(settings.snowflake)
    captcha.configure_security(admin_security)
    csrf.configure_security(admin_security)
    password.configure_security(admin_security)
    rate_limit.configure_security(admin_security)
    session_security.configure_security(admin_security)

    # 同步内置超管角色与管理操作项目录（幂等）
    from toolhive.infrastructure.database import async_session_factory
    from toolhive.services.role_service import RoleService
    async with async_session_factory() as session:
        role_svc = RoleService(session)
        await role_svc.ensure_super_admin_role()
        await role_svc.sync_operation_codes()

    outbox_worker = None
    if settings.outbox.enabled:
        from toolhive.services.outbox.worker import OutboxWorker
        outbox_worker = OutboxWorker(settings.outbox)
        await outbox_worker.start()
    yield
    if outbox_worker is not None:
        await outbox_worker.stop()
    # 关闭时清理资源
    from toolhive.infrastructure.redis import close_redis
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

# 入口校验（A10）：可信代理范围、入口标识与来源 IP
from toolhive.api.ingress import IngressMiddleware  # noqa: E402

app.add_middleware(IngressMiddleware, network=settings.network)

# 挂载管理侧子应用：/api/admin/**
from toolhive.api.admin.router import admin_app  # noqa: E402

app.mount("/api/admin", admin_app)

# 挂载运行侧子应用：/api/runtime/**
from toolhive.api.runtime.router import runtime_app  # noqa: E402

app.mount("/api/runtime", runtime_app)


@app.get("/health")
async def health():
    return {"status": "ok"}
