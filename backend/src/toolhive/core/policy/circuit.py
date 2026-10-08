"""Provider 级熔断；generation 防止旧执行结果关闭新的熔断窗口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from toolhive.core.policy.degradation import Mechanism, dependency_failed
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.store import PolicyStore


@dataclass(frozen=True)
class CircuitSettings:
    threshold: int = 5
    window_ms: int = 60000
    open_ms: int = 30000
    probe_lease_ms: int = 10000

    def __post_init__(self) -> None:
        if min(self.threshold, self.window_ms, self.open_ms, self.probe_lease_ms) <= 0:
            raise ValueError("熔断参数必须为正数")


@dataclass(frozen=True)
class CircuitPermit:
    provider_id: int
    generation: str
    owner: str = field(repr=False)
    degraded: bool = False


class CircuitPolicy:
    def __init__(self, store: PolicyStore, settings: CircuitSettings | None = None) -> None:
        self.store, self.settings = store, settings or CircuitSettings()

    async def _run(
        self, provider_id: int, op: str, generation: str = "", owner: str = ""
    ) -> list[Any]:
        cfg = self.settings
        return await self.store.run(
            "policy_circuit",
            [self.store.key(f"circuit:{provider_id}")],
            [
                op,
                uuid4().hex,
                cfg.threshold,
                cfg.window_ms,
                cfg.open_ms,
                cfg.probe_lease_ms,
                generation,
                owner,
            ],
        )

    async def allow(self, provider_id: int) -> CircuitPermit:
        try:
            result = await self._run(provider_id, "allow")
        except RedisError:
            dependency_failed(Mechanism.CIRCUIT)
            return CircuitPermit(provider_id, "", "", True)
        if not int(result[0]):
            raise PolicyError("TH_CIRCUIT_OPEN", retry_after_ms=self.settings.open_ms)
        return CircuitPermit(provider_id, str(result[1]), str(result[2]))

    async def report(self, permit: CircuitPermit, *, healthy: bool) -> None:
        """F 执行器决定哪些网络/上游故障算 failure，业务 4xx 不自动计入。"""
        await self._finish(permit, "success" if healthy else "failure")

    async def abandon(self, permit: CircuitPermit) -> None:
        """未出站释放半开探针；旧 owner 不能影响后来探针。"""
        await self._finish(permit, "abandon")

    async def _finish(self, permit: CircuitPermit, operation: str) -> None:
        if permit.degraded:
            return
        try:
            await self._run(permit.provider_id, operation, permit.generation, permit.owner)
        except RedisError:
            dependency_failed(Mechanism.CIRCUIT)
