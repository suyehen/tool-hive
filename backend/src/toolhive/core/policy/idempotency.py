"""指纹绑定、版本固定与 owner CAS；unknown 永不自动重发。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from toolhive.core.policy.contracts import Authorization, normalize_selector
from toolhive.core.policy.degradation import Mechanism, dependency_failed
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.store import PolicyStore

logger = logging.getLogger(__name__)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def request_fingerprint(
    tool_id: int,
    selector: str | None,
    arguments: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    context_fields: frozenset[str] = frozenset(),
) -> str:
    """只纳入显式白名单中的结果相关 context；trace/deadline/确认令牌不参与。"""
    forbidden = {"trace_id", "deadline", "deadline_ms", "confirmation_token"}
    if forbidden & context_fields:
        raise ValueError("运行控制字段不能参与业务指纹")
    selected = {key: value for key, value in (context or {}).items() if key in context_fields}
    raw = canonical_json([str(tool_id), normalize_selector(selector), arguments, selected])
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class CallRecord:
    key: str = field(repr=False)
    fingerprint: str
    principal_id: int
    tool_id: int
    version_id: int
    binding_digest: str
    state: str
    owner: str = field(repr=False)
    lease_until: int
    payload: str | None = field(default=None, repr=False)


class IdempotencyPolicy:
    def __init__(
        self, store: PolicyStore, *, ttl_seconds: int = 86400, max_result_bytes: int = 262144
    ) -> None:
        if ttl_seconds <= 0 or max_result_bytes <= 0:
            raise ValueError("幂等保留参数必须为正数")
        self.store, self.ttl_seconds, self.max_result_bytes = store, ttl_seconds, max_result_bytes

    def key(self, principal_id: int, caller_key: str) -> str:
        if not caller_key or len(caller_key.encode()) > 4096:
            raise PolicyError("TH_PARAMETER_INVALID")
        digest = hashlib.sha256(caller_key.encode()).hexdigest()
        return self.store.key(f"idempotency:{principal_id}:{digest}")

    async def _run(self, key: str, args: list[str | int]) -> tuple[str, CallRecord | None]:
        try:
            result = await self.store.run("policy_idempotency", [key], args)
        except RedisError:
            dependency_failed(Mechanism.IDEMPOTENCY)
            raise AssertionError("closed dependency must raise") from None
        status = str(result[0])
        pairs = result[1]
        if not pairs:
            return status, None
        data = dict(zip(pairs[::2], pairs[1::2], strict=True))
        record = CallRecord(
            key,
            data["fingerprint"],
            int(data["principal_id"]),
            int(data["tool_id"]),
            int(data["version_id"]),
            data["binding_digest"],
            data["state"],
            data["owner"],
            int(data["lease_until"]),
            data.get("payload"),
        )
        if record.state == "unknown":
            logger.warning("idempotency_unknown", extra={"tool_id": record.tool_id})
        return status, record

    async def lookup(self, principal_id: int, caller_key: str) -> CallRecord | None:
        _, record = await self._run(self.key(principal_id, caller_key), ["lookup", "", ""])
        return record

    async def claim(
        self,
        principal_id: int,
        caller_key: str,
        fingerprint: str,
        authorization: Authorization,
        *,
        binding_digest: str,
        lease_ms: int,
    ) -> CallRecord:
        """竞争期间可能已经 completed；调用方重放该记录，不能继续出站。"""
        if lease_ms <= 0 or principal_id != authorization.principal_id:
            raise ValueError("claim 主体或租期无效")
        status, record = await self._run(
            self.key(principal_id, caller_key),
            [
                "claim",
                fingerprint,
                uuid4().hex,
                lease_ms,
                str(principal_id),
                str(authorization.tool.id),
                str(authorization.version.id),
                binding_digest,
            ],
        )
        self._check_status(status)
        assert record is not None
        # 过期 reserved 继承原版本；调用方必须先用 lookup 固定版本再授权。
        if record.version_id != authorization.version.id or record.tool_id != authorization.tool.id:
            raise PolicyError("TH_IDEMPOTENCY_KEY_REUSED")
        return record

    @staticmethod
    def _check_status(status: str) -> None:
        codes = {
            "REUSED": "TH_IDEMPOTENCY_KEY_REUSED",
            "UNKNOWN": "TH_EXECUTION_OUTCOME_UNKNOWN",
            "BUSY": "TH_IDEMPOTENCY_IN_PROGRESS",
            "STALE": "TH_IDEMPOTENCY_IN_PROGRESS",
        }
        if status in codes:
            raise PolicyError(codes[status])

    def replay(
        self, record: CallRecord, fingerprint: str, authorization: Authorization
    ) -> dict[str, Any] | None:
        """只在完成新鲜授权与请求约束检查后调用；失效授权不得重放历史结果。"""
        if (
            record.principal_id != authorization.principal_id
            or record.tool_id != authorization.tool.id
        ):
            raise PolicyError("TH_TOOL_NOT_FOUND")
        if record.fingerprint != fingerprint:
            raise PolicyError("TH_IDEMPOTENCY_KEY_REUSED")
        if record.version_id != authorization.version.id:
            raise PolicyError("TH_TOOL_NOT_FOUND")
        if record.state == "unknown":
            raise PolicyError("TH_EXECUTION_OUTCOME_UNKNOWN")
        if record.state == "completed":
            assert record.payload is not None
            outcome: dict[str, Any] = json.loads(record.payload)
            return outcome
        # reserved 是否过期以 Redis TIME 的 claim CAS 为准。
        return None

    async def transition(self, record: CallRecord, operation: str, *, lease_ms: int = 0) -> None:
        if operation not in {"dispatch", "unknown", "abandon", "reap", "renew"}:
            raise ValueError("幂等操作无效")
        if operation == "renew" and lease_ms <= 0:
            raise ValueError("续租需要正租期")
        status, _ = await self._run(
            record.key, [operation, record.fingerprint, record.owner, lease_ms]
        )
        self._check_status(status)

    async def complete(
        self,
        record: CallRecord,
        *,
        trace_id: str,
        result: object,
        error_code: str | None = None,
    ) -> None:
        if len(trace_id) > 64:
            raise ValueError("trace_id 过长")
        retained = len(canonical_json(result).encode()) <= self.max_result_bytes
        payload = canonical_json(
            {
                "trace_id": trace_id,
                "result": result if retained else None,
                "result_retained": retained,
                "error_code": error_code,
            }
        )
        status, _ = await self._run(
            record.key,
            [
                "complete",
                record.fingerprint,
                record.owner,
                0,
                payload,
                self.ttl_seconds,
            ],
        )
        self._check_status(status)
