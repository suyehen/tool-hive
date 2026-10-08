"""凭据仓储：管理查询只返回掩码；运行面可读取活跃密文，不负责解密。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.crypto import CipherError, parse_kek_id
from toolhive.adapters.db.repository import EntityNotFoundError
from toolhive.core.domain.contracts import Actor, IdFactory
from toolhive.core.domain.errors import InvalidDefinitionError
from toolhive.core.domain.models import AuditLog, Credential
from toolhive.core.domain.transactions import domain_write


@dataclass(frozen=True)
class CredentialView:
    id: int
    name: str
    kind: str
    status: str
    masked_value: str = "********"


@dataclass(frozen=True)
class EncryptedCredential:
    id: int
    kind: str
    kek_id: str | None
    rotated_at: datetime | None
    ciphertext: bytes = field(repr=False)
    meta: dict[str, Any] = field(repr=False)


class CredentialRepository:
    def __init__(self, session: AsyncSession, next_id: IdFactory) -> None:
        self.session = session
        self.next_id = next_id

    async def store_encrypted(
        self,
        identifier: int,
        name: str,
        kind: str,
        ciphertext: bytes,
        kek_id: str,
        meta: dict[str, Any],
        actor: Actor,
    ) -> CredentialView:
        """E6 先按 ID 绑定 AAD 加密，再交由本仓储入库；此处从不接受明文。"""
        if identifier <= 0 or not name.strip() or len(name) > 128:
            raise InvalidDefinitionError("凭据标识或名称无效")
        if kind not in {"static_header", "bearer"}:
            raise InvalidDefinitionError("M0 不支持该凭据类型")
        allowed_meta = {"header_name"} if kind == "static_header" else set()
        if set(meta) - allowed_meta:
            raise InvalidDefinitionError("凭据元数据包含未知字段")
        if kind == "static_header" and (
            not isinstance(meta.get("header_name"), str) or not meta["header_name"]
        ):
            raise InvalidDefinitionError("static_header 缺少 header_name")
        try:
            actual_kek = parse_kek_id(ciphertext)
        except CipherError:
            raise InvalidDefinitionError("密文封装无效") from None
        if actual_kek != kek_id:
            raise InvalidDefinitionError("密文与 KEK 标识不一致")
        async with domain_write(self.session):
            entity = Credential(
                id=identifier,
                name=name,
                kind=kind,
                status="active",
                ciphertext=ciphertext,
                kek_id=kek_id,
                meta=deepcopy(meta),
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            event = AuditLog(
                id=self.next_id(),
                action="credential.create",
                object_type="credential",
                object_id=identifier,
            )
            event.stamp_create(actor.id, actor.name)
            self.session.add(event)
            await self.session.flush()
            return CredentialView(identifier, name, kind, "active")

    async def get_by_id(self, identifier: int) -> CredentialView | None:
        row = (
            await self.session.execute(
                select(
                    Credential.id,
                    Credential.name,
                    Credential.kind,
                    Credential.status,
                ).where(Credential.id == identifier)
            )
        ).one_or_none()
        return CredentialView(*row) if row is not None else None

    async def load_active_ciphertext(self, identifier: int) -> EncryptedCredential:
        row = (
            await self.session.execute(
                select(
                    Credential.id,
                    Credential.kind,
                    Credential.kek_id,
                    Credential.rotated_at,
                    Credential.ciphertext,
                    Credential.meta,
                ).where(Credential.id == identifier, Credential.status == "active")
            )
        ).one_or_none()
        if row is None or row.ciphertext is None:
            raise InvalidDefinitionError("活跃凭据不可用")
        return EncryptedCredential(
            row.id,
            row.kind,
            row.kek_id,
            row.rotated_at,
            row.ciphertext,
            deepcopy(row.meta),
        )

    async def revoke(self, identifier: int, actor: Actor) -> None:
        async with domain_write(self.session):
            entity = await self.session.scalar(
                select(Credential)
                .where(
                    Credential.id == identifier,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if entity is None:
                raise EntityNotFoundError("Credential", identifier)
            entity.status = "revoked"
            entity.touch(actor.id, actor.name)
            event = AuditLog(
                id=self.next_id(),
                action="credential.revoke",
                object_type="credential",
                object_id=identifier,
            )
            event.stamp_create(actor.id, actor.name)
            self.session.add(event)
            await self.session.flush()
