"""运行 API：高风险执行确认申请与一次性校验。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.runtime.v1.schemas import (
    ConfirmRequest,
    ConfirmResponse,
    VerifyConfirmRequest,
    VerifyConfirmResponse,
)
from toolhive.infrastructure.database import get_db
from toolhive.runtime.confirmations.service import ConfirmationService
from toolhive.runtime.errors import (
    RUNTIME_PARAMETER_INVALID,
    RuntimeApiError,
)
from toolhive.runtime.tool_control.service import CallControlService

router = APIRouter(prefix="/v1/confirmations", tags=["runtime-confirmations"])


@router.post("", response_model=ConfirmResponse)
async def request_confirmation(
    request: Request,
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """为高风险工具申请一次性确认令牌。"""
    identity = request.state.caller_identity
    decision = await CallControlService(db).evaluate_executable(
        identity.system.system_id, body.tool_code, version=body.version,
    )
    if not decision.allowed:
        raise RuntimeApiError(
            decision.error_code or RUNTIME_PARAMETER_INVALID,
            decision.error_message or "工具不可用",
            400,
        )
    if not decision.confirmation_required:
        raise RuntimeApiError(
            RUNTIME_PARAMETER_INVALID, "该工具不需要确认", 400,
        )
    assert decision.tool is not None and decision.version is not None
    record, token = await ConfirmationService(db).request_confirmation(
        system_id=identity.system.system_id,
        tool_id=decision.tool.id,
        tool_code=body.tool_code,
        version_id=decision.version.id,
        trace_id=identity.trace_id,
    )
    return ConfirmResponse(
        confirmation_id=record.id,
        tool_code=body.tool_code,
        token=token,
        expires_at=record.expires_at,
        trace_id=identity.trace_id,
    )


@router.post("/verify", response_model=VerifyConfirmResponse)
async def verify_confirmation(
    request: Request,
    body: VerifyConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """一次性校验确认令牌（校验即消费，不可重放）。"""
    identity = request.state.caller_identity
    record = await ConfirmationService(db).verify_confirmation(
        system_id=identity.system.system_id,
        confirmation_id=body.confirmation_id,
        token=body.token,
        trace_id=identity.trace_id,
    )
    return VerifyConfirmResponse(
        valid=True,
        tool_code=record.tool_code,
        trace_id=identity.trace_id,
    )
