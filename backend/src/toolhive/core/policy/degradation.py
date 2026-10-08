"""依赖故障矩阵；放行防滥用故障时也必须发出告警。"""

from __future__ import annotations

import logging
from enum import StrEnum

from toolhive.core.policy.errors import PolicyError

_log = logging.getLogger(__name__)


class Mechanism(StrEnum):
    IDEMPOTENCY = "idempotency"
    CONFIRMATION = "confirmation"
    QPS = "qps"
    DAILY = "daily"
    CONCURRENCY = "concurrency"
    VISIBILITY = "visibility"
    CIRCUIT = "circuit"
    DATABASE = "database"


class FailureMode(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    BYPASS = "bypass"


FAILURE_MODES = {
    Mechanism.IDEMPOTENCY: FailureMode.CLOSED,
    Mechanism.CONFIRMATION: FailureMode.CLOSED,
    Mechanism.QPS: FailureMode.OPEN,
    Mechanism.DAILY: FailureMode.OPEN,
    Mechanism.CONCURRENCY: FailureMode.OPEN,
    Mechanism.VISIBILITY: FailureMode.BYPASS,
    Mechanism.CIRCUIT: FailureMode.OPEN,
    Mechanism.DATABASE: FailureMode.CLOSED,
}


def dependency_failed(mechanism: Mechanism) -> FailureMode:
    mode = FAILURE_MODES[mechanism]
    # 异常文本可能包含连接串、命令参数或凭据，不使用 exc_info。
    _log.error(
        "policy_dependency_failed",
        extra={
            "mechanism": mechanism.value,
            "failure_mode": mode.value,
        },
    )
    if mode == FailureMode.CLOSED:
        raise PolicyError("TH_DEPENDENCY_UNAVAILABLE") from None
    return mode
