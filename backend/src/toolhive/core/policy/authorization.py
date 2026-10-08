"""执行授权总是查询数据库；可见集合缓存仅供发现路径使用。"""

from __future__ import annotations

import json
from typing import TypeVar, cast

from redis.exceptions import RedisError
from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.db.base import Base
from toolhive.core.domain.errors import InvalidDefinitionError
from toolhive.core.domain.grants import matches_scope, scope_predicate
from toolhive.core.domain.models import (
    ExecutionBinding,
    Grant,
    Principal,
    Provider,
    Tool,
    ToolChannel,
    ToolVersion,
)
from toolhive.core.policy.constraints import constraints_allow
from toolhive.core.policy.contracts import (
    Authorization,
    GrantPolicy,
    RequestContext,
    normalize_selector,
)
from toolhive.core.policy.degradation import Mechanism, dependency_failed
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.store import PolicyStore

Model = TypeVar("Model", bound=Base)


class AuthorizationService:
    def __init__(self, session: AsyncSession, store: PolicyStore, *, visible_ttl: int = 60) -> None:
        if not 1 <= visible_ttl <= 60:
            raise ValueError("可见集合 TTL 必须为 1–60 秒")
        self.session, self.store, self.visible_ttl = session, store, visible_ttl

    async def resolve(
        self,
        principal_id: int,
        code: str,
        selector: str | None = None,
        *,
        pinned_version_id: int | None = None,
    ) -> Authorization:
        """pinned_version_id 只能来自指纹匹配的幂等记录；仍检查当前授权。"""
        try:
            with self.session.no_autoflush:
                return await self._resolve(principal_id, code, selector, pinned_version_id)
        except SQLAlchemyError:
            dependency_failed(Mechanism.DATABASE)
            raise AssertionError("closed dependency must raise") from None
        except InvalidDefinitionError:
            raise PolicyError("TH_INTERNAL_ERROR") from None

    async def _resolve(
        self,
        principal_id: int,
        code: str,
        selector: str | None,
        pinned: int | None,
    ) -> Authorization:
        async def one(model: type[Model], *predicates: ColumnElement[bool]) -> Model | None:
            return cast(
                Model | None,
                await self.session.scalar(
                    select(model).where(*predicates).execution_options(populate_existing=True)
                ),
            )

        principal = await one(Principal, Principal.id == principal_id)
        tool = await one(Tool, Tool.code == code)
        if principal is None or principal.status != "enabled" or tool is None:
            raise PolicyError("TH_TOOL_NOT_FOUND")
        stable = await one(
            ToolChannel, ToolChannel.tool_id == tool.id, ToolChannel.name == "stable"
        )
        if tool.status not in {"enabled", "stale"} or stable is None:
            raise PolicyError("TH_TOOL_NOT_FOUND")
        stable_version = await one(ToolVersion, ToolVersion.id == stable.version_id)
        if stable_version is None or stable_version.status != "published":
            raise PolicyError("TH_TOOL_NOT_FOUND")
        selected = normalize_selector(selector)
        if pinned is not None:
            version = await one(ToolVersion, ToolVersion.id == pinned)
        elif selected.startswith("channel:"):
            channel = await one(
                ToolChannel,
                ToolChannel.tool_id == tool.id,
                ToolChannel.name == selected[8:],
            )
            version = (
                None
                if channel is None
                else await one(ToolVersion, ToolVersion.id == channel.version_id)
            )
        else:
            version = await one(
                ToolVersion, ToolVersion.tool_id == tool.id, ToolVersion.version == selected[8:]
            )
        if (
            version is None
            or version.tool_id != tool.id
            or version.status != "published"
            or not version.executable
        ):
            raise PolicyError("TH_TOOL_NOT_FOUND")
        binding = await one(ExecutionBinding, ExecutionBinding.version_id == version.id)
        provider = (
            None if binding is None else await one(Provider, Provider.id == binding.provider_id)
        )
        if binding is None or provider is None or provider.status != "enabled":
            raise PolicyError("TH_TOOL_NOT_FOUND")
        grants = (
            await self.session.scalars(
                select(Grant)
                .where(
                    Grant.principal_id == principal_id,
                    Grant.status == "active",
                )
                .execution_options(populate_existing=True)
            )
        ).all()
        matching = tuple(GrantPolicy.from_model(g) for g in grants if matches_scope(g, version))
        if not matching:
            raise PolicyError("TH_TOOL_NOT_FOUND")
        return Authorization(principal_id, tool, version, binding, provider, matching)

    async def visible_ids(self, principal_id: int) -> set[int]:
        """只缓存范围展开，不缓存请求 IP、时间窗、配额或执行授权结论。"""
        try:
            principal = await self.session.scalar(
                select(Principal)
                .where(
                    Principal.id == principal_id,
                )
                .execution_options(populate_existing=True)
            )
            if principal is None or principal.status != "enabled":
                return set()
            generation_key = self.store.key(f"visible_ver:{principal_id}")
            cache_key: str | None = None
            # 管理事务中的未提交变更不能写入跨请求缓存。
            if not (self.session.new or self.session.dirty or self.session.deleted):
                try:
                    generation = await self.store.redis.get(generation_key) or "0"
                    if isinstance(generation, bytes):
                        generation = generation.decode()
                    cache_key = self.store.key(f"visible:{principal_id}:{generation}")
                    cached = await self.store.redis.get(cache_key)
                    if cached is not None:
                        values = json.loads(cached)
                        if isinstance(values, list) and all(type(v) is int for v in values):
                            return set(values)
                except (RedisError, ValueError):
                    dependency_failed(Mechanism.VISIBILITY)
                    cache_key = None
            grants = (
                await self.session.scalars(
                    select(Grant)
                    .where(
                        Grant.principal_id == principal_id,
                        Grant.status == "active",
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
            identifiers: set[int] = set()
            for grant in grants:
                identifiers.update(
                    (
                        await self.session.scalars(select(Tool.id).where(scope_predicate(grant)))
                    ).all()
                )
            if cache_key is not None:
                try:
                    await self.store.redis.set(
                        cache_key, json.dumps(sorted(identifiers)), ex=self.visible_ttl
                    )
                except RedisError:
                    dependency_failed(Mechanism.VISIBILITY)
            return identifiers
        except SQLAlchemyError:
            dependency_failed(Mechanism.DATABASE)
            raise AssertionError("closed dependency must raise") from None

        except InvalidDefinitionError:
            raise PolicyError("TH_INTERNAL_ERROR") from None

    async def invalidate(self, principal_ids: list[int] | None = None) -> None:
        """Outbox 消费者在成功后才 ACK；重复消费仅增加 generation，安全可重试。

        Tool/Provider 变更传 None，保守失效全部 Principal，覆盖变更前的范围。
        """
        if principal_ids is None:
            principal_ids = list((await self.session.scalars(select(Principal.id))).all())
        pipeline = self.store.redis.pipeline(transaction=True)
        for identifier in principal_ids:
            pipeline.incr(self.store.key(f"visible_ver:{identifier}"))
        await pipeline.execute()

    async def filter_discoverable(
        self,
        principal_id: int,
        context: RequestContext,
    ) -> set[int]:
        """H 在排序前调用；缓存候选经新鲜授权、发布快照及请求约束过滤。"""
        candidates = await self.visible_ids(principal_id)
        try:
            codes = (
                await self.session.execute(
                    select(Tool.id, Tool.code).where(Tool.id.in_(candidates))
                )
            ).all()
        except SQLAlchemyError:
            dependency_failed(Mechanism.DATABASE)
            raise AssertionError("closed dependency must raise") from None
        allowed = set()
        for identifier, code in codes:
            try:
                authorization = await self.resolve(principal_id, code)
            except PolicyError as exc:
                if exc.code == "TH_TOOL_NOT_FOUND":
                    continue
                raise
            if authorization.version.discoverable and all(
                constraints_allow(grant.constraints, context) for grant in authorization.grants
            ):
                allowed.add(identifier)
        return allowed
