"""ToolHive 应用入口。"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager

from fastapi import FastAPI

# 启动阶段统一加载配置：--config 或 TOOLHIVE_CONFIG_FILE 指定外挂 YAML
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--config", dest="config_file", default=None)
_args, _ = _parser.parse_known_args()

from toolhive.config import load_settings

settings = load_settings(_args.config_file)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    # 启动阶段：初始化基础设施与管理安全配置分区
    from toolhive.infrastructure.database import init_infrastructure
    from toolhive.infrastructure.redis import init_redis

    init_infrastructure(settings.infrastructure, debug=settings.debug)
    init_redis(settings.infrastructure)

    from toolhive.services.security import (
        csrf,
        password,
        rate_limit,
        session as session_security,
        totp,
    )
    admin_security = settings.admin_security
    csrf.configure_security(admin_security)
    password.configure_security(admin_security)
    rate_limit.configure_security(admin_security)
    session_security.configure_security(admin_security)
    totp.configure_security(admin_security)

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


@app.get("/health")
async def health():
    return {"status": "ok"}
