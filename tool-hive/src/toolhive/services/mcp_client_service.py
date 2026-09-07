"""MCP 客户端管理服务：生命周期、令牌、来源规则与授权范围。"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import (
    IPRuleStatus,
    McpClientStatus,
    McpTokenStatus,
    ToolScopeStatus,
    ToolScopeType,
)
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.mcp_client import McpClient
from toolhive.models.mcp_client_ip_rule import McpClientIpRule
from toolhive.models.mcp_client_scope import McpClientScope
from toolhive.models.mcp_client_token import McpClientToken
from toolhive.services.audit_service import AuditService, get_current_operator_id
from toolhive.services.catalog_scope_validator import CatalogScopeValidator
from toolhive.services.security.password import hash_password

_MCP_CLIENT_PREFIX = "mcp_"


class McpClientService:
    """MCP 客户端生命周期与令牌 / 来源 / 授权管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def generate_client_code() -> str:
        """生成客户端公开编码（唯一，稳定）。"""
        return f"{_MCP_CLIENT_PREFIX}{uuid.uuid4().hex}"

    # ── 客户端 CRUD 与生命周期 ──

    async def list_clients(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[McpClient], int]:
        """分页查询 MCP 客户端，支持关键词与状态过滤。"""
        conditions = []
        kw = keyword.strip() if keyword else ""
        if kw:
            pattern = f"%{kw}%"
            conditions.append(
                or_(
                    McpClient.client_code.ilike(pattern),
                    McpClient.name.ilike(pattern),
                )
            )
        if status:
            conditions.append(McpClient.status == status)
        total = await self.db.scalar(
            select(func.count()).select_from(McpClient).where(*conditions)
        )
        result = await self.db.execute(
            select(McpClient)
            .where(*conditions)
            .order_by(McpClient.create_time)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_by_client_code(self, client_code: str) -> McpClient:
        """按客户端公开编码查询，不存在时抛 404。"""
        client = await self.db.scalar(
            select(McpClient).where(McpClient.client_code == client_code)
        )
        if client is None:
            raise NotFoundError(f"MCP 客户端不存在: {client_code}")
        return client

    @transactional()
    async def create_client(
        self,
        *,
        name: str,
        description: str | None = None,
    ) -> McpClient:
        """创建草稿客户端，公开编码由服务端生成。"""
        name_value = (name or "").strip()
        if not name_value:
            raise ValidationError("客户端名称不能为空")
        client = McpClient(
            client_code=self.generate_client_code(),
            name=name_value,
            description=description,
            status=McpClientStatus.DRAFT,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(client)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.create",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={
                "client_code": client.client_code,
                "name": name_value,
            },
        )
        return client

    @transactional()
    async def update_client(
        self,
        client_code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        expected_row_version: int | None = None,
    ) -> McpClient:
        """更新客户端资料（仅更新显式提供的字段）。"""
        client = await self.get_by_client_code(client_code)
        if client.status == McpClientStatus.REVOKED:
            raise ConflictError("已注销的客户端不可修改")
        if expected_row_version is not None:
            await self.db.refresh(client, with_for_update=True)
            if client.row_version != expected_row_version:
                raise ConflictError("数据已被他人修改，请刷新后重试")
        if name is not None:
            name_value = name.strip()
            if not name_value:
                raise ValidationError("客户端名称不能为空")
            client.name = name_value
        if description is not None:
            client.description = description
        client.update_time = datetime.now(UTC)
        client.update_by = get_current_operator_id()
        client.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.update",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "name": client.name},
        )
        return client

    @transactional()
    async def enable(self, client_code: str) -> McpClient:
        """启用客户端：前置要求存在 ACTIVE 令牌与 ACTIVE 来源 IP 规则。"""
        client = await self.get_by_client_code(client_code)
        if client.status == McpClientStatus.ENABLED:
            raise ConflictError("MCP 客户端已启用")
        if client.status == McpClientStatus.REVOKED:
            raise ConflictError("已注销的客户端不可启用，请先恢复")
        conditions = await self._check_enable_conditions(client.id)
        if conditions:
            raise ValidationError("启用条件不满足: " + "; ".join(conditions))
        client.status = McpClientStatus.ENABLED
        client.update_time = datetime.now(UTC)
        client.update_by = get_current_operator_id()
        client.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.enable",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "status": "enabled"},
        )
        return client

    @transactional()
    async def disable(
        self, client_code: str, reason: str | None = None,
    ) -> McpClient:
        """停用客户端（允许后续重新启用）。"""
        client = await self.get_by_client_code(client_code)
        if client.status != McpClientStatus.ENABLED:
            raise ConflictError("仅启用状态的客户端可停用")
        client.status = McpClientStatus.DISABLED
        client.deactivated_reason = reason
        client.update_time = datetime.now(UTC)
        client.update_by = get_current_operator_id()
        client.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.disable",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "reason": reason},
        )
        return client

    @transactional()
    async def revive(self, client_code: str) -> McpClient:
        """恢复已注销客户端为停用状态。"""
        client = await self.get_by_client_code(client_code)
        if client.status != McpClientStatus.REVOKED:
            raise ConflictError("仅注销状态的客户端可恢复")
        client.status = McpClientStatus.DISABLED
        client.deactivated_reason = None
        client.update_time = datetime.now(UTC)
        client.update_by = get_current_operator_id()
        client.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.revive",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "status": "disabled"},
        )
        return client

    @transactional()
    async def revoke(
        self, client_code: str, reason: str | None = None,
    ) -> McpClient:
        """注销客户端：同时吊销其 ACTIVE 令牌。"""
        client = await self.get_by_client_code(client_code)
        if client.status == McpClientStatus.REVOKED:
            raise ConflictError("客户端已注销")
        await self._revoke_active_tokens(client.id, reason or "客户端注销")
        client.status = McpClientStatus.REVOKED
        client.deactivated_reason = reason
        client.update_time = datetime.now(UTC)
        client.update_by = get_current_operator_id()
        client.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.revoke",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "reason": reason},
        )
        return client

    async def _check_enable_conditions(self, client_id: str) -> list[str]:
        """返回启用前置条件缺口列表（空列表表示满足）。"""
        conditions: list[str] = []
        token_count = await self.db.scalar(
            select(func.count())
            .select_from(McpClientToken)
            .where(
                McpClientToken.client_id == client_id,
                McpClientToken.status == McpTokenStatus.ACTIVE,
            )
        )
        if not token_count:
            conditions.append("缺少 ACTIVE 访问令牌")
        rule_count = await self.db.scalar(
            select(func.count())
            .select_from(McpClientIpRule)
            .where(
                McpClientIpRule.client_id == client_id,
                McpClientIpRule.status == IPRuleStatus.ACTIVE,
            )
        )
        if not rule_count:
            conditions.append("缺少 ACTIVE 来源 IP 规则")
        return conditions

    # ── 令牌 ──

    @transactional()
    async def issue_token(
        self, client_code: str, reason: str | None = None,
    ) -> tuple[McpClientToken, str]:
        """签发新令牌：吊销旧 ACTIVE 令牌后写入新记录，明文只返回一次。"""
        client = await self.get_by_client_code(client_code)
        if client.status == McpClientStatus.REVOKED:
            raise ConflictError("已注销的客户端不可签发令牌")
        await self._revoke_active_tokens(client.id, reason or "令牌轮换")
        token = secrets.token_urlsafe(32)
        record = McpClientToken(
            client_id=client.id,
            token_hash=hash_password(token),
            token_key=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            status=McpTokenStatus.ACTIVE,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(record)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.issue_token",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "token_id": record.id},
        )
        return record, token

    @transactional()
    async def revoke_token(
        self, client_code: str, reason: str | None = None,
    ) -> None:
        """吊销客户端当前 ACTIVE 令牌。"""
        client = await self.get_by_client_code(client_code)
        await self._revoke_active_tokens(client.id, reason or "管理端吊销")
        AuditService(self.db).add_record(
            action="mcp_client.revoke_token",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "reason": reason},
        )

    async def _revoke_active_tokens(self, client_id: str, reason: str) -> None:
        """将客户端现有 ACTIVE 令牌置为 REVOKED。"""
        result = await self.db.execute(
            select(McpClientToken).where(
                McpClientToken.client_id == client_id,
                McpClientToken.status == McpTokenStatus.ACTIVE,
            )
        )
        now = datetime.now(UTC)
        for record in result.scalars().all():
            record.status = McpTokenStatus.REVOKED
            record.revoked_at = now
            record.revoked_reason = reason
            record.update_time = now
            record.update_by = get_current_operator_id()
            record.row_version += 1

    # ── 来源 IP 规则 ──

    async def list_ip_rules(self, client_code: str) -> list[McpClientIpRule]:
        """查询客户端来源 IP 规则。"""
        client = await self.get_by_client_code(client_code)
        result = await self.db.execute(
            select(McpClientIpRule)
            .where(McpClientIpRule.client_id == client.id)
            .order_by(McpClientIpRule.create_time)
        )
        return list(result.scalars().all())

    @transactional()
    async def add_ip_rule(
        self,
        client_code: str,
        *,
        ip_cidr: str,
        description: str | None = None,
    ) -> McpClientIpRule:
        """新增来源 IP 规则（编码统一 trim 后入库）。"""
        client = await self.get_by_client_code(client_code)
        value = ip_cidr.strip()
        if not value:
            raise ValidationError("来源 IP 规则不能为空")
        rule = McpClientIpRule(
            client_id=client.id,
            ip_cidr=value,
            description=description,
            status=IPRuleStatus.ACTIVE,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(rule)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.add_ip_rule",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "ip_cidr": value},
        )
        return rule

    @transactional()
    async def update_ip_rule_status(
        self, rule_id: str, status: str,
    ) -> None:
        """启停来源 IP 规则。"""
        rule = await self.db.get(McpClientIpRule, rule_id)
        if rule is None:
            raise NotFoundError(f"来源 IP 规则不存在: {rule_id}")
        if status not in tuple(IPRuleStatus):
            raise ValidationError("无效的来源 IP 规则状态")
        rule.status = status
        rule.update_time = datetime.now(UTC)
        rule.update_by = get_current_operator_id()
        rule.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.ip_rule_status",
            object_type="mcp_client",
            object_id=rule.client_id,
            after_summary={"rule_id": rule.id, "status": status},
        )

    # ── 授权范围 ──

    async def list_scopes(
        self, client_code: str,
    ) -> list[McpClientScope]:
        """查询客户端授权范围。"""
        client = await self.get_by_client_code(client_code)
        result = await self.db.execute(
            select(McpClientScope)
            .where(McpClientScope.client_id == client.id)
            .order_by(McpClientScope.scope_type, McpClientScope.scope_code)
        )
        return list(result.scalars().all())

    async def list_scopes_with_reference(
        self, client_code: str,
    ) -> list[dict]:
        """查询客户端授权范围并附带 Catalog 引用状态。"""
        client = await self.get_by_client_code(client_code)
        scopes = await self.list_scopes(client_code)
        refs = await CatalogScopeValidator(self.db).reference_map(scopes)
        rows = []
        for scope in scopes:
            exists, archived = refs.get(
                (scope.scope_type, scope.scope_code), (False, False),
            )
            rows.append(
                {
                    "id": scope.id,
                    "client_id": client.id,
                    "scope_type": scope.scope_type,
                    "scope_code": scope.scope_code,
                    "status": scope.status,
                    "row_version": scope.row_version,
                    "created_at": scope.create_time,
                    "reference_exists": exists,
                    "reference_archived": archived,
                }
            )
        return rows

    @transactional()
    async def replace_scopes(
        self,
        client_code: str,
        items: list[dict],
    ) -> list[McpClientScope]:
        """全量替换客户端授权范围（先整体校验再替换）。"""
        client = await self.get_by_client_code(client_code)
        for item in items:
            if item["scope_type"] not in tuple(ToolScopeType):
                raise ValidationError(f"无效的工具范围类型: {item['scope_type']}")
            if item["status"] not in tuple(ToolScopeStatus):
                raise ValidationError(f"无效的工具范围状态: {item['status']}")
        await CatalogScopeValidator(self.db).validate_items(items)
        old_scopes = await self.list_scopes(client_code)
        for scope in old_scopes:
            await self.db.delete(scope)
        new_scopes: list[McpClientScope] = []
        for item in items:
            scope = McpClientScope(
                client_id=client.id,
                scope_type=item["scope_type"],
                scope_code=str(item["scope_code"]).strip(),
                status=item["status"],
                create_time=datetime.now(UTC),
                create_by=get_current_operator_id(),
            )
            self.db.add(scope)
            new_scopes.append(scope)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_client.replace_scopes",
            object_type="mcp_client",
            object_id=client.id,
            after_summary={"client_code": client.client_code, "count": len(new_scopes)},
        )
        return new_scopes
