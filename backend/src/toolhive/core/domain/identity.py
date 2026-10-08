"""Principal 与 API Key 生命周期；入口层负责 HTTP/MCP 认证映射。"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.domain.contracts import Actor, IdFactory
from toolhive.core.domain.errors import InvalidApiKeyError, InvalidDefinitionError
from toolhive.core.domain.models import ApiKey, AuditLog, Principal
from toolhive.core.domain.repositories import PrincipalRepository
from toolhive.core.domain.transactions import domain_write

_HASHER = PasswordHasher()


@dataclass(frozen=True)
class IssuedApiKey:
    id: int
    prefix: str
    plaintext: str = field(repr=False)


class IdentityService:
    def __init__(self, session: AsyncSession, next_id: IdFactory) -> None:
        self.session = session
        self.next_id = next_id

    async def create_principal(self, name: str, kind: str, actor: Actor) -> Principal:
        if kind not in {"user", "service", "agent"} or not name.strip() or len(name) > 128:
            raise InvalidDefinitionError("主体类型或名称无效")
        async with domain_write(self.session):
            entity = Principal(id=self.next_id(), name=name, type=kind)
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            await self.session.flush()
            return entity

    async def issue_key(
        self,
        principal_id: int,
        actor: Actor,
        expires_at: datetime | None = None,
    ) -> IssuedApiKey:
        if expires_at is not None and (
            expires_at.tzinfo is None or expires_at <= datetime.now(UTC)
        ):
            raise InvalidDefinitionError("API Key 到期时间必须为未来且带时区")
        prefix = secrets.token_hex(8)
        plaintext = f"th_{prefix}.{secrets.token_urlsafe(32)}"
        hashed = await asyncio.to_thread(_HASHER.hash, plaintext)
        async with domain_write(self.session):
            principal = await PrincipalRepository(self.session).require_for_update(principal_id)
            if principal.status != "enabled":
                raise InvalidDefinitionError("主体未启用")
            entity = ApiKey(
                id=self.next_id(),
                principal_id=principal_id,
                key_prefix=prefix,
                key_hash=hashed,
                status="active",
                expires_at=expires_at,
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            self._audit("api_key.create", entity.id, actor)
            await self.session.flush()
            return IssuedApiKey(entity.id, prefix, plaintext)

    async def revoke_key(self, key_id: int, actor: Actor) -> None:
        async with domain_write(self.session):
            entity = await self.session.scalar(
                select(ApiKey)
                .where(
                    ApiKey.id == key_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if entity is None:
                raise InvalidApiKeyError("认证失败")
            entity.status = "revoked"
            entity.touch(actor.id, actor.name)
            self._audit("api_key.revoke", entity.id, actor)
            await self.session.flush()

    async def authenticate(self, plaintext: str) -> Principal:
        # 长度限制先于 Argon2，避免异常输入导致无界哈希工作。
        prefix, separator, secret = plaintext.removeprefix("th_").partition(".")
        if not plaintext.startswith("th_") or not separator or not secret or len(plaintext) > 256:
            raise InvalidApiKeyError("认证失败")
        entity = await self.session.scalar(
            select(ApiKey)
            .where(
                ApiKey.key_prefix == prefix,
            )
            .execution_options(populate_existing=True)
        )
        if entity is None or entity.status != "active":
            raise InvalidApiKeyError("认证失败")
        now = datetime.now(UTC)
        if entity.expires_at is not None and entity.expires_at <= now:
            raise InvalidApiKeyError("认证失败")
        verified_hash = entity.key_hash
        try:
            await asyncio.to_thread(_HASHER.verify, verified_hash, plaintext)
        except (VerificationError, InvalidHashError):
            raise InvalidApiKeyError("认证失败") from None
        # 哈希期间可能吊销或过期，再读取当前记录；普通读不持有长时间行锁。
        await self.session.refresh(entity)
        principal = await PrincipalRepository(self.session).get_by_id(entity.principal_id)
        if (
            entity.status != "active"
            or entity.key_hash != verified_hash
            or (entity.expires_at is not None and entity.expires_at <= datetime.now(UTC))
            or principal is None
            or principal.status != "enabled"
        ):
            raise InvalidApiKeyError("认证失败")
        used_at = datetime.now(UTC)
        # 最后以条件 UPDATE 记录使用，防止哈希计算期间吊销后仍写入活跃使用状态。
        used = await self.session.scalar(
            update(ApiKey)
            .where(
                ApiKey.id == entity.id,
                ApiKey.key_hash == verified_hash,
                ApiKey.principal_id == principal.id,
                ApiKey.status == "active",
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > used_at),
            )
            .values(last_used_at=used_at)
            .returning(ApiKey.id)
        )
        if used is None:
            raise InvalidApiKeyError("认证失败")
        return principal

    def _audit(self, action: str, identifier: int, actor: Actor) -> None:
        event = AuditLog(
            id=self.next_id(),
            action=action,
            object_type="api_key",
            object_id=identifier,
        )
        event.stamp_create(actor.id, actor.name)
        self.session.add(event)
