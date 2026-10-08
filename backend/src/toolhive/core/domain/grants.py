"""Grant 数据与范围解析；不评估请求约束、不操作 Redis 配额。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.db.repository import EntityNotFoundError
from toolhive.core.domain.contracts import Actor, IdFactory
from toolhive.core.domain.errors import InvalidDefinitionError
from toolhive.core.domain.grant_constraints import parse_constraints
from toolhive.core.domain.models import AuditLog, Grant, OutboxEvent, Tool, ToolVersion
from toolhive.core.domain.repositories import PrincipalRepository, ToolRepository
from toolhive.core.domain.transactions import domain_write


def matches_scope(grant: Grant, tool: Tool | ToolVersion) -> bool:
    """对版本快照同样适用；tool grant 使用不随 code 改名变化的 tool_id。"""
    if grant.status != "active":
        return False
    if grant.scope_type == "domain":
        return grant.scope_value == tool.domain
    if grant.scope_type == "system":
        return grant.scope_value == f"{tool.domain}.{tool.system}"
    if grant.scope_type == "tag":
        return grant.scope_value in tool.tags
    identifier = tool.id if isinstance(tool, Tool) else tool.tool_id
    return grant.scope_type == "tool" and grant.scope_value == str(identifier)


def scope_predicate(grant: Grant) -> ColumnElement[bool]:
    if grant.scope_type == "domain":
        return Tool.domain == grant.scope_value
    if grant.scope_type == "system":
        domain, separator, system = grant.scope_value.partition(".")
        if not separator or not domain or not system:
            raise InvalidDefinitionError("system 范围必须为 domain.system")
        return and_(Tool.domain == domain, Tool.system == system)
    if grant.scope_type == "tag":
        return Tool.tags.contains([grant.scope_value])
    if grant.scope_type == "tool" and grant.scope_value.isdecimal():
        return Tool.id == int(grant.scope_value)
    raise InvalidDefinitionError("授权范围无效")


class GrantRepository:
    def __init__(self, session: AsyncSession, next_id: IdFactory) -> None:
        self.session = session
        self.next_id = next_id

    async def create(
        self,
        principal_id: int,
        scope_type: str,
        scope_value: str,
        actor: Actor,
        quota: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
    ) -> Grant:
        if scope_type not in {"domain", "system", "tag", "tool"}:
            raise InvalidDefinitionError("授权范围类型无效")
        if not scope_value or len(scope_value) > 160:
            raise InvalidDefinitionError("授权范围值无效")
        if scope_type == "system":
            domain, separator, system = scope_value.partition(".")
            if not separator or not domain or not system:
                raise InvalidDefinitionError("system 范围必须为 domain.system")
        quota = deepcopy(quota or {})
        parse_constraints(constraints or {})
        for name, value in quota.items():
            if name not in {"qps", "daily", "concurrency"} or (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise InvalidDefinitionError("配额必须为已知维度的正整数")
        async with domain_write(self.session):
            await PrincipalRepository(self.session).require(principal_id)
            if scope_type == "tool":
                if not scope_value.isdecimal() or int(scope_value) <= 0:
                    raise InvalidDefinitionError("tool 范围必须为不可变工具 ID")
                scope_value = str(int(scope_value))
                await ToolRepository(self.session).require(int(scope_value))
            entity = Grant(
                id=self.next_id(),
                principal_id=principal_id,
                scope_type=scope_type,
                scope_value=scope_value,
                quota=quota,
                constraints=deepcopy(constraints or {}),
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            self._changed(entity, actor, "grant.create")
            await self.session.flush()
            return entity

    async def disable(self, identifier: int, actor: Actor) -> None:
        async with domain_write(self.session):
            entity = (
                await self.session.scalars(
                    select(Grant)
                    .where(Grant.id == identifier)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).one_or_none()
            if entity is None:
                raise EntityNotFoundError("Grant", identifier)
            entity.status = "disabled"
            entity.touch(actor.id, actor.name)
            self._changed(entity, actor, "grant.disable")
            await self.session.flush()

    async def list_active(self, principal_id: int) -> list[Grant]:
        return list(
            (
                await self.session.scalars(
                    select(Grant)
                    .where(
                        Grant.principal_id == principal_id,
                        Grant.status == "active",
                    )
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def expand_tool_ids(self, principal_id: int) -> set[int]:
        grants = await self.list_active(principal_id)
        if not grants:
            return set()
        statement = select(Tool.id).where(or_(*(scope_predicate(grant) for grant in grants)))
        return set((await self.session.scalars(statement)).all())

    def _changed(self, grant: Grant, actor: Actor, action: str) -> None:
        for event in (
            AuditLog(
                id=self.next_id(), action=action, object_type="grant_rule", object_id=grant.id
            ),
            OutboxEvent(
                id=self.next_id(),
                event_type="visibility.invalidate",
                object_type="principal",
                object_id=grant.principal_id,
                payload={"principal_id": grant.principal_id},
            ),
        ):
            event.stamp_create(actor.id, actor.name)
            self.session.add(event)
