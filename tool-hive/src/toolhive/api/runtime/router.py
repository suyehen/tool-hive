"""运行侧子应用：签名认证、范围/流量控制与统一错误链。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse

from toolhive.api.deps import get_runtime_security
from toolhive.api.runtime.v1.confirmations import router as confirmations_router
from toolhive.api.runtime.v1.tools import router as tools_router
from toolhive.runtime.errors import (
    RUNTIME_INTERNAL_ERROR,
    RuntimeApiError,
)
from toolhive.runtime.middleware import RuntimeSecurityMiddleware
from toolhive.runtime.tracing.service import new_trace_id

logger = logging.getLogger(__name__)

runtime_app = FastAPI(
    title="ToolHive Runtime API",
    version="0.1.0",
)

runtime_app.add_middleware(
    RuntimeSecurityMiddleware,
    runtime_security=get_runtime_security(),
)


@runtime_app.exception_handler(RuntimeApiError)
async def _runtime_error_handler(request: Request, exc: RuntimeApiError):
    """运行 API 业务错误 → 统一错误体。"""
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "trace_id": trace_id},
    )


@runtime_app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception):
    """未处理异常 → 500，不泄露内部信息。"""
    trace_id = getattr(request.state, "trace_id", None) or new_trace_id()
    logger.exception("runtime unhandled error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "code": RUNTIME_INTERNAL_ERROR,
            "message": "内部错误",
            "trace_id": trace_id,
        },
    )


router = APIRouter(prefix="/v1", tags=["runtime"])


@router.post("/ping")
async def runtime_ping(request: Request):
    """签名探活接口（阶段 2 验收闭环用，阶段 4 由真实业务接口替代）。"""
    identity = request.state.caller_identity
    return {
        "status": "ok",
        "system_id": identity.system.system_id,
        "trace_id": request.state.trace_id,
    }


runtime_app.include_router(router)
runtime_app.include_router(tools_router)
runtime_app.include_router(confirmations_router)
