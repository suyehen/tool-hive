"""工具版本治理：行锁串行化同工具变更，事务内发布投影与 Outbox。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.db.repository import EntityNotFoundError
from toolhive.core.domain.contracts import (
    BINDING_FIELDS,
    DEFINITION_FIELDS,
    Actor,
    BindingDefinition,
    IdFactory,
    ToolDefinition,
)
from toolhive.core.domain.errors import InvalidDefinitionError, InvalidTransitionError
from toolhive.core.domain.models import (
    AuditLog,
    ExecutionBinding,
    OutboxEvent,
    ReviewRecord,
    Tool,
    ToolChannel,
    ToolVersion,
)
from toolhive.core.domain.repositories import ProviderRepository, ToolRepository, VersionRepository
from toolhive.core.domain.transactions import domain_write


def _definition_values(definition: ToolDefinition) -> dict[str, Any]:
    definition.validate()
    values = asdict(definition)
    values["tags"] = list(definition.tags)
    values["executable"] = definition.executable
    return values


def _version_definition(version: ToolVersion) -> ToolDefinition:
    return ToolDefinition(
        **{
            name: deepcopy(getattr(version, name))
            for name in DEFINITION_FIELDS
            if name != "executable"
        }
    )


class CatalogService:
    """不做请求授权，不提交外层事务；ID 工厂必须使用持有租约的雪花生成器。"""

    def __init__(self, session: AsyncSession, next_id: IdFactory) -> None:
        self.session = session
        self.next_id = next_id

    async def create_tool(
        self,
        code: str,
        source_ref: str,
        name: str,
        provider_id: int,
        actor: Actor,
    ) -> Tool:
        if not code.strip() or len(code) > 160 or not source_ref.strip() or len(source_ref) > 512:
            raise InvalidDefinitionError("工具标识无效")
        if not name.strip() or len(name) > 200:
            raise InvalidDefinitionError("工具名称无效")
        async with domain_write(self.session):
            await ProviderRepository(self.session).require(provider_id)
            entity = Tool(
                id=self.next_id(),
                code=code,
                source_ref=source_ref,
                provider_id=provider_id,
                name=name,
                executable=False,
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            self._audit("tool.create", "tool", entity.id, actor)
            await self.session.flush()
            return entity

    async def create_draft(
        self,
        tool_id: int,
        version: str,
        definition: ToolDefinition,
        binding: BindingDefinition,
        actor: Actor,
    ) -> ToolVersion:
        values = _definition_values(definition)
        if not version.strip() or len(version) > 32:
            raise InvalidDefinitionError("版本标识为空或过长")
        async with domain_write(self.session):
            tool = await ToolRepository(self.session).require_for_update(tool_id)
            self._mutable_tool(tool)
            await self._validate_binding(binding)
            entity = ToolVersion(
                id=self.next_id(),
                tool_id=tool_id,
                version=version,
                status="draft",
                **values,
            )
            entity.stamp_create(actor.id, actor.name)
            self.session.add(entity)
            await self.session.flush()
            record = ExecutionBinding(
                id=self.next_id(),
                version_id=entity.id,
                **asdict(binding),
            )
            record.stamp_create(actor.id, actor.name)
            self.session.add(record)
            await self.session.flush()
            return entity

    async def revise_draft(
        self,
        version_id: int,
        definition: ToolDefinition,
        binding: BindingDefinition,
        actor: Actor,
    ) -> ToolVersion:
        values = _definition_values(definition)
        async with domain_write(self.session):
            tool, version = await self._lock_version(version_id)
            self._mutable_tool(tool)
            self._expect(version, "draft")
            await self._validate_binding(binding)
            for name, value in values.items():
                setattr(version, name, value)
            record = await self._binding(version.id)
            for name, value in asdict(binding).items():
                setattr(record, name, value)
            record.touch(actor.id, actor.name)
            version.touch(actor.id, actor.name)
            await self.session.flush()
            return version

    async def reopen(self, version_id: int, actor: Actor) -> ToolVersion:
        async with domain_write(self.session):
            tool, version = await self._lock_version(version_id)
            self._mutable_tool(tool)
            self._expect(version, "rejected")
            version.status = "draft"
            version.touch(actor.id, actor.name)
            self._audit("version.reopen", "tool_version", version.id, actor)
            await self.session.flush()
            return version

    async def submit(
        self, version_id: int, actor: Actor, comment: str | None = None
    ) -> ToolVersion:
        async with domain_write(self.session):
            tool, version = await self._lock_version(version_id)
            self._mutable_tool(tool)
            self._expect(version, "draft")
            definition = _version_definition(version)
            definition.validate()
            if version.executable != definition.executable:
                raise InvalidDefinitionError("执行标记与版本语义不一致")
            record = await self._binding(version.id)
            await self._validate_binding(
                BindingDefinition(**{name: getattr(record, name) for name in BINDING_FIELDS})
            )
            self._review(version, "submit", "pending_review", actor, comment)
            version.submitted_at = datetime.now(UTC)
            await self.session.flush()
            return version

    async def approve(
        self, version_id: int, actor: Actor, comment: str | None = None
    ) -> ToolVersion:
        async with domain_write(self.session):
            tool, version = await self._lock_version(version_id)
            self._mutable_tool(tool)
            self._expect(version, "pending_review")
            record = await self._binding(version.id)
            await self._validate_binding(
                BindingDefinition(**{name: getattr(record, name) for name in BINDING_FIELDS})
            )
            self._review(version, "approve", "published", actor, comment)
            version.published_at = datetime.now(UTC)
            # 先 flush 状态，随后通道查询才能读到 published。
            await self.session.flush()
            stable = await self._channel(tool.id, "stable")
            if stable is None:
                await self._point_channel(tool, version, "stable", actor)
            await self.session.flush()
            return version

    async def reject(
        self, version_id: int, actor: Actor, comment: str | None = None
    ) -> ToolVersion:
        async with domain_write(self.session):
            tool, version = await self._lock_version(version_id)
            self._mutable_tool(tool)
            self._expect(version, "pending_review")
            self._review(version, "reject", "rejected", actor, comment)
            await self.session.flush()
            return version

    async def publish_channel(
        self,
        tool_id: int,
        version_id: int,
        channel: str,
        actor: Actor,
    ) -> ToolChannel:
        if channel not in {"stable", "beta", "canary"}:
            raise InvalidDefinitionError("通道名称无效")
        async with domain_write(self.session):
            tool = await ToolRepository(self.session).require_for_update(tool_id)
            self._mutable_tool(tool)
            version = await VersionRepository(self.session).require_for_update(version_id)
            if version.tool_id != tool_id:
                raise InvalidDefinitionError("通道版本不属于该工具")
            self._expect(version, "published")
            result = await self._point_channel(tool, version, channel, actor)
            await self.session.flush()
            return result

    async def set_tool_status(self, tool_id: int, status: str, actor: Actor) -> Tool:
        if status not in {"enabled", "disabled", "stale", "archived"}:
            raise InvalidDefinitionError("工具状态无效")
        async with domain_write(self.session):
            tool = await ToolRepository(self.session).require_for_update(tool_id)
            self._mutable_tool(tool)
            tool.status = status
            tool.touch(actor.id, actor.name)
            self._audit("tool.status", "tool", tool.id, actor)
            self._outbox("visibility.invalidate", tool.id, actor)
            await self.session.flush()
            return tool

    async def _lock_version(self, version_id: int) -> tuple[Tool, ToolVersion]:
        # 全部同工具写入先锁 Tool，再锁 Version，避免审批与通道切换锁顺序相反。
        tool_id = await self.session.scalar(
            select(ToolVersion.tool_id).where(ToolVersion.id == version_id),
        )
        if tool_id is None:
            raise EntityNotFoundError("ToolVersion", version_id)
        tool = await ToolRepository(self.session).require_for_update(tool_id)
        version = await VersionRepository(self.session).require_for_update(version_id)
        return tool, version

    async def _binding(self, version_id: int) -> ExecutionBinding:
        result = await self.session.scalar(
            select(ExecutionBinding)
            .where(
                ExecutionBinding.version_id == version_id,
            )
            .execution_options(populate_existing=True)
        )
        if result is None:
            raise InvalidDefinitionError("版本缺少执行绑定")
        return result

    async def _validate_binding(self, binding: BindingDefinition) -> None:
        provider = await ProviderRepository(self.session).require(binding.provider_id)
        if provider.status != "enabled":
            raise InvalidDefinitionError("Provider 未启用")
        binding.validate(provider.type)
        if provider.type == "http" and not provider.base_url:
            raise InvalidDefinitionError("HTTP Provider 缺少地址")

    async def _channel(self, tool_id: int, name: str) -> ToolChannel | None:
        return (
            await self.session.scalars(
                select(ToolChannel)
                .where(
                    ToolChannel.tool_id == tool_id,
                    ToolChannel.name == name,
                )
                .execution_options(populate_existing=True)
            )
        ).one_or_none()

    async def _point_channel(
        self,
        tool: Tool,
        version: ToolVersion,
        name: str,
        actor: Actor,
    ) -> ToolChannel:
        channel = await self._channel(tool.id, name)
        if channel is not None and channel.version_id == version.id:
            return channel
        if channel is None:
            channel = ToolChannel(
                id=self.next_id(),
                tool_id=tool.id,
                name=name,
                version_id=version.id,
            )
            channel.stamp_create(actor.id, actor.name)
            self.session.add(channel)
        else:
            channel.version_id = version.id
            channel.touch(actor.id, actor.name)
        if name == "stable":
            for field in DEFINITION_FIELDS:
                setattr(tool, field, deepcopy(getattr(version, field)))
            tool.touch(actor.id, actor.name)
            self._outbox("tool.index.refresh", tool.id, actor)
            self._outbox("visibility.invalidate", tool.id, actor)
        self._audit("channel.publish", "tool", tool.id, actor)
        return channel

    def _review(
        self,
        version: ToolVersion,
        action: str,
        target: str,
        actor: Actor,
        comment: str | None,
    ) -> None:
        record = ReviewRecord(
            id=self.next_id(),
            version_id=version.id,
            action=action,
            from_status=version.status,
            to_status=target,
            comment=comment,
        )
        record.stamp_create(actor.id, actor.name)
        self.session.add(record)
        version.status = target
        version.review_comment = comment
        version.touch(actor.id, actor.name)

    def _audit(self, action: str, kind: str, identifier: int, actor: Actor) -> None:
        event = AuditLog(id=self.next_id(), action=action, object_type=kind, object_id=identifier)
        event.stamp_create(actor.id, actor.name)
        self.session.add(event)

    def _outbox(self, kind: str, tool_id: int, actor: Actor) -> None:
        event = OutboxEvent(
            id=self.next_id(),
            event_type=kind,
            object_type="tool",
            object_id=tool_id,
            payload={"tool_id": tool_id},
        )
        event.stamp_create(actor.id, actor.name)
        self.session.add(event)

    @staticmethod
    def _expect(version: ToolVersion, status: str) -> None:
        if version.status != status:
            raise InvalidTransitionError("当前版本状态不允许该操作")

    @staticmethod
    def _mutable_tool(tool: Tool) -> None:
        if tool.status == "archived":
            raise InvalidTransitionError("归档工具不可修改")
