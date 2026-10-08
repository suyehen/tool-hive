"""Provider 实时连接配置治理；出站校验与加解密属于 E。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.db.repository import OptimisticLockError
from toolhive.core.domain.contracts import Actor, IdFactory
from toolhive.core.domain.errors import InvalidDefinitionError, InvalidTransitionError
from toolhive.core.domain.models import AuditLog, Credential, OutboxEvent, Provider
from toolhive.core.domain.repositories import ProviderRepository
from toolhive.core.domain.transactions import domain_write


class ProviderService(ProviderRepository):
    def __init__(self, session: AsyncSession, next_id: IdFactory) -> None:
        super().__init__(session)
        self.next_id = next_id

    async def register(
        self,
        code: str,
        name: str,
        kind: str,
        base_url: str | None,
        actor: Actor,
        auth_ref: int | None = None,
    ) -> Provider:
        self._validate(kind, base_url)
        if not code.strip() or len(code) > 64 or not name.strip() or len(name) > 128:
            raise InvalidDefinitionError("Provider 标识或名称无效")
        async with domain_write(self.session):
            await self._credential(auth_ref)
            entity = Provider(
                id=self.next_id(),
                code=code,
                name=name,
                type=kind,
                base_url=base_url,
                auth_ref=auth_ref,
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            self._audit(
                entity, actor, {}, {"type": kind, "base_url": base_url, "auth_ref": auth_ref}
            )
            await self.session.flush()
            return entity

    async def revise(
        self,
        identifier: int,
        expected_row_version: int,
        *,
        base_url: str | None,
        auth_ref: int | None,
        actor: Actor,
    ) -> Provider:
        async with domain_write(self.session):
            entity = await self.require_for_update(identifier)
            if entity.status == "archived":
                raise InvalidTransitionError("归档 Provider 不可修改")
            if entity.row_version != expected_row_version:
                raise OptimisticLockError("Provider", identifier, expected_row_version)
            self._validate(entity.type, base_url)
            await self._credential(auth_ref)
            before = {
                "base_url": entity.base_url,
                "auth_ref": entity.auth_ref,
                "row_version": entity.row_version,
            }
            entity.base_url = base_url
            entity.auth_ref = auth_ref
            entity.touch(actor.id, actor.name)
            after = {"base_url": base_url, "auth_ref": auth_ref, "row_version": entity.row_version}
            self._audit(entity, actor, before, after)
            await self.session.flush()
            return entity

    async def _credential(self, identifier: int | None) -> None:
        if identifier is None:
            return
        credential = await self.session.get(Credential, identifier)
        if credential is None or credential.status != "active":
            raise InvalidDefinitionError("认证引用不是活跃凭据")

    async def set_status(
        self,
        identifier: int,
        expected_row_version: int,
        status: str,
        actor: Actor,
    ) -> Provider:
        if status not in {"enabled", "disabled", "archived"}:
            raise InvalidDefinitionError("Provider 状态无效")
        async with domain_write(self.session):
            entity = await self.require_for_update(identifier)
            if entity.status == "archived":
                raise InvalidTransitionError("归档 Provider 不可修改")
            if entity.row_version != expected_row_version:
                raise OptimisticLockError("Provider", identifier, expected_row_version)
            before = {"status": entity.status, "row_version": entity.row_version}
            entity.status = status
            entity.touch(actor.id, actor.name)
            invalidation = OutboxEvent(
                id=self.next_id(), event_type="visibility.invalidate",
                object_type="provider", object_id=entity.id, payload={},
            )
            invalidation.stamp_create(actor.id, actor.name)
            self.session.add(invalidation)
            self._audit(
                entity, actor, before, {"status": status, "row_version": entity.row_version}
            )
            await self.session.flush()
            return entity

    @staticmethod
    def _validate(kind: str, base_url: str | None) -> None:
        if kind not in {"http", "local"}:
            raise InvalidDefinitionError("M0 仅支持 http/local Provider")
        if kind == "local":
            if base_url is not None:
                raise InvalidDefinitionError("local Provider 不使用上游地址")
            return
        try:
            url = urlsplit(base_url or "")
            invalid = (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or (
                    url.username is not None
                    or url.password is not None
                    or url.query
                    or url.fragment
                )
            )
        except ValueError:
            invalid = True
        if invalid or base_url is None or len(base_url) > 512:
            raise InvalidDefinitionError("HTTP Provider 地址无效或含敏感认证信息")

    def _audit(
        self,
        entity: Provider,
        actor: Actor,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> None:
        event = AuditLog(
            id=self.next_id(),
            action="provider.configure",
            object_type="provider",
            object_id=entity.id,
            before_summary=deepcopy(before),
            after_summary=deepcopy(after),
        )
        event.stamp_create(actor.id, actor.name)
        self.session.add(event)
