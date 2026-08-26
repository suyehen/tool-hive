"""调用系统管理服务。"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.constants import CALLER_SYSTEM_ID_PREFIX
from toolhive.core.enums import (
    CallerSystemStatus,
    IPRuleStatus,
    PublicKeyStatus,
    ToolScopeStatus,
    ToolScopeType,
)
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.caller_ip_rule import CallerIPRule
from toolhive.models.caller_public_key import CallerPublicKey
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.models.caller_system import CallerSystem
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.runtime.authentication.verifiers import get_verifier
from toolhive.services.audit_service import AuditService, get_current_operator_id

logger = logging.getLogger(__name__)


def build_caller_system_filters(
    keyword: str | None = None,
    status: str | None = None,
    environment: str | None = None,
) -> list:
    """构造调用系统列表过滤条件：关键词命中编码/名称/system_id，状态与环境精确匹配。"""
    conditions: list = []
    kw = keyword.strip() if keyword else ""
    if kw:
        pattern = f"%{kw}%"
        conditions.append(
            or_(
                CallerSystem.code.ilike(pattern),
                CallerSystem.name.ilike(pattern),
                CallerSystem.system_id.ilike(pattern),
            )
        )
    if status:
        conditions.append(CallerSystem.status == status)
    if environment:
        conditions.append(CallerSystem.environment == environment)
    return conditions


class CallerSystemService:
    """调用系统生命周期管理。"""

    def __init__(
        self,
        db: AsyncSession,
        runtime_security: RuntimeSecuritySettings | None = None,
    ):
        self.db = db
        self.runtime_security = runtime_security

    # ═════════════════════════════════════════════════════════════
    # 生命周期
    # ═════════════════════════════════════════════════════════════

    @staticmethod
    def generate_system_id() -> str:
        return f"{CALLER_SYSTEM_ID_PREFIX}{uuid.uuid4().hex}"

    @transactional()
    async def create_draft(
        self,
        name: str,
        code: str,
        environment: str,
        description: str | None = None,
        belonging_party: str | None = None,
        owner: str | None = None,
        contact: str | None = None,
        owner_email: str | None = None,
        tags: list[str] | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> CallerSystem:
        if environment not in ("development", "staging", "production"):
            raise ValidationError("环境必须是 development、staging 或 production")
        # 同一环境下系统编码不可重复
        existing = await self.db.scalar(
            select(CallerSystem).where(
                CallerSystem.environment == environment,
                CallerSystem.code == code,
            )
        )
        if existing:
            raise ConflictError(f"该环境下系统编码 '{code}' 已被使用")

        # 创建调用系统：显式写入创建时间与当前操作人 ID
        system = CallerSystem(
            system_id=self.generate_system_id(),
            name=name,
            description=description,
            environment=environment,
            belonging_party=belonging_party,
            code=code,
            owner=owner,
            contact=contact,
            owner_email=owner_email,
            status=CallerSystemStatus.DRAFT,
            effective_from=effective_from,
            effective_to=effective_to,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        if tags is not None:
            system.set_tags(tags)
        self.db.add(system)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.create",
            object_type="caller_system",
            object_id=system.system_id,
            after_summary={
                "system_id": system.system_id,
                "name": name,
                "code": code,
                "environment": environment,
            },
        )
        return system

    @transactional()
    async def update_system(
        self,
        system_id: str,
        name: str | None = None,
        description: str | None = None,
        belonging_party: str | None = None,
        owner: str | None = None,
        contact: str | None = None,
        owner_email: str | None = None,
        tags: list[str] | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
        expected_row_version: int | None = None,
    ) -> CallerSystem:
        """更新调用系统主记录（仅更新显式提供的字段）。"""
        system = await self.get_by_system_id(system_id)
        if (
            expected_row_version is not None
            and system.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")

        def _dt(value):
            return value.isoformat() if value else None

        before = {
            "name": system.name,
            "description": system.description,
            "belonging_party": system.belonging_party,
            "owner": system.owner,
            "contact": system.contact,
            "owner_email": system.owner_email,
            "tags": system.get_tags(),
            "effective_from": _dt(system.effective_from),
            "effective_to": _dt(system.effective_to),
        }
        if name is not None:
            system.name = name
        if description is not None:
            system.description = description
        if belonging_party is not None:
            system.belonging_party = belonging_party
        if owner is not None:
            system.owner = owner
        if contact is not None:
            system.contact = contact
        if owner_email is not None:
            system.owner_email = owner_email
        if tags is not None:
            system.set_tags(tags)
        if effective_from is not None:
            system.effective_from = effective_from
        if effective_to is not None:
            system.effective_to = effective_to
        # 更新调用系统：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        after = {
            "name": system.name,
            "description": system.description,
            "belonging_party": system.belonging_party,
            "owner": system.owner,
            "contact": system.contact,
            "owner_email": system.owner_email,
            "tags": system.get_tags(),
            "effective_from": _dt(system.effective_from),
            "effective_to": _dt(system.effective_to),
        }
        AuditService(self.db).add_record(
            action="caller_system.update",
            object_type="caller_system",
            object_id=system_id,
            before_summary=before,
            after_summary=after,
        )
        await self.db.flush()
        return system

    @transactional()
    async def enable(self, system_id: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status == CallerSystemStatus.ENABLED:
            raise ConflictError("调用系统已启用")

        # 前置条件检查
        conditions = await self._check_enable_conditions(system_id)
        if conditions:
            raise ValidationError("启用条件不满足: " + "; ".join(conditions))

        system.status = CallerSystemStatus.ENABLED
        # 启用调用系统：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.enable",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"status": "enabled"},
        )
        return system

    # ═════════════════════════════════════════════════════════════
    # 运行策略
    # ═════════════════════════════════════════════════════════════

    async def get_runtime_policy(
        self, system_id: str,
    ) -> CallerRuntimePolicy | None:
        """查询运行策略；调用系统不存在时抛 404，策略未配置时返回 None。"""
        await self.get_by_system_id(system_id)
        return await self.db.scalar(
            select(CallerRuntimePolicy).where(
                CallerRuntimePolicy.system_id == system_id,
            )
        )

    @transactional()
    async def save_runtime_policy(
        self,
        system_id: str,
        allowed_api_patterns: list[str],
        qps_limit: int,
        concurrency_limit: int,
        quota_per_day: int,
        request_timeout_seconds: int,
        circuit_breaker_enabled: bool,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
        expected_row_version: int | None = None,
    ) -> CallerRuntimePolicy:
        """整存运行策略（每调用系统一条，不存在则创建）。"""
        await self.get_by_system_id(system_id)
        if not allowed_api_patterns:
            raise ValidationError("运行 API 范围不能为空")

        policy = await self.db.scalar(
            select(CallerRuntimePolicy).where(
                CallerRuntimePolicy.system_id == system_id,
            )
        )
        if policy is None:
            # 创建运行策略：显式写入创建时间与当前操作人 ID
            policy = CallerRuntimePolicy(
                system_id=system_id,
                allowed_api_patterns=json.dumps(
                    allowed_api_patterns, ensure_ascii=False,
                ),
                qps_limit=qps_limit,
                concurrency_limit=concurrency_limit,
                quota_per_day=quota_per_day,
                request_timeout_seconds=request_timeout_seconds,
                circuit_breaker_enabled=circuit_breaker_enabled,
                effective_from=effective_from,
                effective_to=effective_to,
                create_time=datetime.now(UTC),
                create_by=get_current_operator_id(),
            )
            self.db.add(policy)
        else:
            if (
                expected_row_version is not None
                and policy.row_version != expected_row_version
            ):
                raise ConflictError("策略已被他人修改，请刷新后重试")
            policy.allowed_api_patterns = json.dumps(
                allowed_api_patterns, ensure_ascii=False,
            )
            policy.qps_limit = qps_limit
            policy.concurrency_limit = concurrency_limit
            policy.quota_per_day = quota_per_day
            policy.request_timeout_seconds = request_timeout_seconds
            policy.circuit_breaker_enabled = circuit_breaker_enabled
            policy.effective_from = effective_from
            policy.effective_to = effective_to
            # 更新运行策略：记录修改时间与当前操作人
            policy.update_time = datetime.now(UTC)
            policy.update_by = get_current_operator_id()
            policy.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_policy.save",
            object_type="caller_system",
            object_id=system_id,
            after_summary={
                "allowed_api_patterns": allowed_api_patterns,
                "qps_limit": qps_limit,
                "concurrency_limit": concurrency_limit,
                "quota_per_day": quota_per_day,
                "request_timeout_seconds": request_timeout_seconds,
                "circuit_breaker_enabled": circuit_breaker_enabled,
            },
        )
        return policy

    # ═════════════════════════════════════════════════════════════
    # 工具范围
    # ═════════════════════════════════════════════════════════════

    async def list_tool_scopes(
        self, system_id: str,
    ) -> list[CallerToolScope]:
        """查询调用系统的工具/能力包范围。"""
        await self.get_by_system_id(system_id)
        result = await self.db.execute(
            select(CallerToolScope)
            .where(CallerToolScope.system_id == system_id)
            .order_by(CallerToolScope.scope_type, CallerToolScope.scope_code),
        )
        return list(result.scalars().all())

    @transactional()
    async def replace_tool_scopes(
        self,
        system_id: str,
        items: list[dict],
    ) -> list[CallerToolScope]:
        """全量替换工具范围（先删旧记录再写入新集合）。"""
        await self.get_by_system_id(system_id)

        # 先整体校验新集合，避免删除旧记录后才发现输入非法
        for item in items:
            scope_type = item["scope_type"]
            status = item["status"]
            if scope_type not in tuple(ToolScopeType):
                raise ValidationError(f"无效的工具范围类型: {scope_type}")
            if status not in tuple(ToolScopeStatus):
                raise ValidationError(f"无效的工具范围状态: {status}")

        old_scopes = await self.list_tool_scopes(system_id)
        for scope in old_scopes:
            await self.db.delete(scope)

        new_scopes: list[CallerToolScope] = []
        for item in items:
            # 写入新的工具范围：显式记录创建时间与当前操作人 ID
            scope = CallerToolScope(
                system_id=system_id,
                scope_type=item["scope_type"],
                scope_code=item["scope_code"],
                status=item["status"],
                create_time=datetime.now(UTC),
                create_by=get_current_operator_id(),
            )
            self.db.add(scope)
            new_scopes.append(scope)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_tool_scope.replace",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"count": len(new_scopes)},
        )
        return new_scopes

    # ═════════════════════════════════════════════════════════════
    # 紧急禁用
    # ═════════════════════════════════════════════════════════════

    @transactional()
    async def emergency_disable(
        self, system_id: str, reason: str,
    ) -> CallerSystem:
        """系统级紧急禁用（仅对已启用系统生效，运行侧应立即拒绝）。"""
        system = await self.get_by_system_id(system_id)
        if system.status != CallerSystemStatus.ENABLED:
            raise ConflictError("只有已启用的调用系统可以紧急禁用")
        system.emergency_disabled = True
        system.emergency_disabled_reason = reason
        system.emergency_disabled_at = datetime.now(UTC)
        # 紧急禁用：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.emergency_disable",
            object_type="caller_system",
            object_id=system_id,
            reason=reason,
            after_summary={"emergency_disabled": True},
        )
        return system

    @transactional()
    async def emergency_enable(self, system_id: str) -> CallerSystem:
        """解除系统级紧急禁用。"""
        system = await self.get_by_system_id(system_id)
        if not system.emergency_disabled:
            raise ConflictError("调用系统未处于紧急禁用状态")
        system.emergency_disabled = False
        system.emergency_disabled_reason = None
        system.emergency_disabled_at = None
        # 解除紧急禁用：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.emergency_enable",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"emergency_disabled": False},
        )
        return system

    @transactional()
    async def disable(self, system_id: str, reason: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status == CallerSystemStatus.DISABLED:
            raise ConflictError("调用系统已停用")
        if system.status == CallerSystemStatus.REVOKED:
            raise ConflictError("调用系统已注销，不能停用")
        system.status = CallerSystemStatus.DISABLED
        system.deactivated_reason = reason
        # 停用调用系统：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.disable",
            object_type="caller_system",
            object_id=system_id,
            reason=reason or None,
            after_summary={"status": "disabled"},
        )
        return system

    @transactional()
    async def revive(self, system_id: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status != CallerSystemStatus.DISABLED:
            raise ConflictError("只有已停用的调用系统可以恢复")
        # 恢复即重新启用：必须满足启用前置条件（与 enable 一致）
        conditions = await self._check_enable_conditions(system_id)
        if conditions:
            raise ValidationError("启用条件不满足: " + "; ".join(conditions))
        system.status = CallerSystemStatus.ENABLED
        system.deactivated_reason = None
        # 紧急禁用为独立覆盖标志：不随停用/恢复清除，运行侧仍拒绝，需显式 emergency-enable
        # 恢复调用系统：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.revive",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"status": "enabled"},
        )
        return system

    @transactional()
    async def revoke(self, system_id: str, reason: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status == CallerSystemStatus.REVOKED:
            raise ConflictError("调用系统已注销")
        system.status = CallerSystemStatus.REVOKED
        system.deactivated_reason = reason
        # 注销调用系统：记录修改时间与当前操作人
        system.update_time = datetime.now(UTC)
        system.update_by = get_current_operator_id()
        # 撤销全部公钥
        keys = await self.list_public_keys(system_id)
        for key in keys:
            if key.status not in (
                PublicKeyStatus.REVOKED,
                PublicKeyStatus.EXPIRED,
            ):
                key.status = PublicKeyStatus.REVOKED
                self.db.add(key)
                key.update_time = datetime.now(UTC)
                key.update_by = get_current_operator_id()
                key.row_version += 1
        system.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_system.revoke",
            object_type="caller_system",
            object_id=system_id,
            reason=reason or None,
            after_summary={"status": "revoked"},
        )
        return system

    # ═════════════════════════════════════════════════════════════
    # 查询
    # ═════════════════════════════════════════════════════════════

    async def get_by_system_id(self, system_id: str) -> CallerSystem:
        system = await self.db.scalar(
            select(CallerSystem).where(CallerSystem.system_id == system_id)
        )
        if system is None:
            raise NotFoundError(f"调用系统不存在: {system_id}")
        return system

    async def get_by_id(self, id: str) -> CallerSystem:
        system = await self.db.get(CallerSystem, id)
        if system is None:
            raise NotFoundError(f"调用系统不存在: {id}")
        return system

    async def list_systems(
        self,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        status: str | None = None,
        environment: str | None = None,
    ) -> tuple[list[CallerSystem], int]:
        conditions = build_caller_system_filters(keyword, status, environment)
        result = await self.db.execute(
            select(CallerSystem)
            .where(*conditions)
            .order_by(CallerSystem.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(result.scalars().all())
        total = await self.db.scalar(
            select(func.count())
            .select_from(CallerSystem)
            .where(*conditions)
        )
        return items, total or 0

    # ═════════════════════════════════════════════════════════════
    # 公钥管理
    # ═════════════════════════════════════════════════════════════

    @staticmethod
    def generate_key_id() -> str:
        return f"key_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def compute_fingerprint(public_key_pem: str) -> str:
        return hashlib.sha256(public_key_pem.encode()).hexdigest()

    @transactional()
    async def add_public_key(
        self,
        system_id: str,
        public_key: str,
        algorithm: str = "RSA-PSS-SHA256",
        effective_to: datetime | None = None,
    ) -> CallerPublicKey:
        await self.get_by_system_id(system_id)  # 确保调用系统存在

        # 按算法注册表获取验签器：未知算法默认拒绝
        verifier = get_verifier(algorithm)
        # 使用运行侧配置的 RSA 最小位长（未注入时使用验签器默认值）
        min_bits = (
            self.runtime_security.signing_key_min_bits
            if self.runtime_security is not None
            else None
        )
        # 校验公钥格式与强度，防止无效或弱公钥入库
        verifier.validate_public_key(public_key, min_bits=min_bits)

        fingerprint = self.compute_fingerprint(public_key_pem=public_key)
        # 检查不重复
        existing = await self.db.scalar(
            select(CallerPublicKey).where(
                CallerPublicKey.fingerprint == fingerprint,
                CallerPublicKey.status.in_(
                    (PublicKeyStatus.PENDING, PublicKeyStatus.ACTIVE),
                ),
            )
        )
        if existing:
            raise ConflictError("该公钥已绑定到其他调用系统")

        # 新增公钥：显式写入创建时间与当前操作人 ID
        key = CallerPublicKey(
            key_id=self.generate_key_id(),
            system_id=system_id,
            public_key=public_key,
            fingerprint=fingerprint,
            algorithm=algorithm,
            status=PublicKeyStatus.PENDING,
            effective_from=datetime.now(UTC),
            effective_to=effective_to,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(key)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_key.add",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"key_id": key.key_id, "fingerprint": key.fingerprint},
        )
        return key

    async def list_public_keys(self, system_id: str) -> list[CallerPublicKey]:
        result = await self.db.execute(
            select(CallerPublicKey).where(CallerPublicKey.system_id == system_id)
        )
        return list(result.scalars().all())

    @transactional()
    async def enable_public_key(self, key_id: str) -> CallerPublicKey:
        key = await self._get_key(key_id)
        if key.status != PublicKeyStatus.PENDING:
            raise ConflictError("只有待启用状态的公钥可以启用")
        key.status = PublicKeyStatus.ACTIVE
        # 启用公钥：记录修改时间与当前操作人
        key.update_time = datetime.now(UTC)
        key.update_by = get_current_operator_id()
        key.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_key.enable",
            object_type="caller_system",
            object_id=key.system_id,
            after_summary={"key_id": key.key_id, "status": "active"},
        )
        return key

    @transactional()
    async def disable_public_key(self, key_id: str) -> CallerPublicKey:
        key = await self._get_key(key_id)
        if key.status not in (PublicKeyStatus.PENDING, PublicKeyStatus.ACTIVE):
            raise ConflictError("只能停用有效或待启用状态的公钥")
        key.status = PublicKeyStatus.DISABLED
        # 停用公钥：记录修改时间与当前操作人
        key.update_time = datetime.now(UTC)
        key.update_by = get_current_operator_id()
        key.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_key.disable",
            object_type="caller_system",
            object_id=key.system_id,
            after_summary={"key_id": key.key_id, "status": "disabled"},
        )
        return key

    @transactional()
    async def revoke_public_key(self, key_id: str) -> CallerPublicKey:
        key = await self._get_key(key_id)
        if key.status == PublicKeyStatus.REVOKED:
            raise ConflictError("该公钥已撤销")
        key.status = PublicKeyStatus.REVOKED
        # 撤销公钥：记录修改时间与当前操作人
        key.update_time = datetime.now(UTC)
        key.update_by = get_current_operator_id()
        key.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_key.revoke",
            object_type="caller_system",
            object_id=key.system_id,
            after_summary={"key_id": key.key_id, "status": "revoked"},
        )
        return key

    # ═════════════════════════════════════════════════════════════
    # IP 规则
    # ═════════════════════════════════════════════════════════════

    @transactional()
    async def add_ip_rule(
        self, system_id: str, ip_cidr: str, description: str | None = None,
    ) -> CallerIPRule:
        await self.get_by_system_id(system_id)
        normalized = self._normalize_cidr(ip_cidr)
        # 新增 IP 规则：显式写入创建时间与当前操作人 ID
        rule = CallerIPRule(
            system_id=system_id,
            ip_cidr=normalized,
            description=description,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(rule)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_ip_rule.add",
            object_type="caller_system",
            object_id=system_id,
            after_summary={"ip_cidr": normalized},
        )
        return rule

    async def list_ip_rules(self, system_id: str) -> list[CallerIPRule]:
        result = await self.db.execute(
            select(CallerIPRule).where(CallerIPRule.system_id == system_id)
        )
        return list(result.scalars().all())

    @transactional()
    async def update_ip_rule_status(self, rule_id: str, status: str) -> CallerIPRule:
        rule = await self.db.get(CallerIPRule, rule_id)
        if rule is None:
            raise NotFoundError(f"IP 规则不存在: {rule_id}")
        if status not in tuple(IPRuleStatus):
            raise ValidationError("无效状态")
        rule.status = IPRuleStatus(status)
        # 更新 IP 规则状态：记录修改时间与当前操作人
        rule.update_time = datetime.now(UTC)
        rule.update_by = get_current_operator_id()
        rule.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="caller_ip_rule.status",
            object_type="caller_system",
            object_id=rule.system_id,
            after_summary={"status": status},
        )
        return rule

    @staticmethod
    def verify_ip(system_id: str, request_ip: str, rules: list[CallerIPRule]) -> bool:
        """校验来源 IP 是否匹配任一有效规则。"""
        active_rules = [
            r for r in rules if r.status == IPRuleStatus.ACTIVE
        ]
        if not active_rules:
            return False

        for rule in active_rules:
            if rule.ip_cidr == "*":
                return True
            try:
                network = ipaddress.IPv4Network(rule.ip_cidr, strict=False)
                addr = ipaddress.IPv4Address(request_ip)
                if addr in network:
                    return True
            except ipaddress.AddressValueError:
                try:
                    network = ipaddress.IPv6Network(rule.ip_cidr, strict=False)
                    addr = ipaddress.IPv6Address(request_ip)
                    if addr in network:
                        return True
                except ipaddress.AddressValueError:
                    continue
        return False

    # ═════════════════════════════════════════════════════════════
    # 内部
    # ═════════════════════════════════════════════════════════════

    async def _check_enable_conditions(self, system_id: str) -> list[str]:
        conditions: list[str] = []
        system = await self.get_by_system_id(system_id)

        if not system.owner:
            conditions.append("缺少负责人")
        if not system.contact:
            conditions.append("缺少联系方式")

        # 检查公钥
        keys = await self.list_public_keys(system_id)
        if not keys:
            conditions.append("缺少认证凭据（公钥）")

        # 检查 IP 规则
        rules = await self.list_ip_rules(system_id)
        if not rules:
            conditions.append("缺少来源 IP 规则")

        # 检查运行策略（API 范围）
        policy = await self.get_runtime_policy(system_id)
        if policy is None or not policy.get_allowed_api_patterns():
            conditions.append("缺少运行策略（运行 API 范围）")

        return conditions

    @staticmethod
    def _normalize_cidr(ip_cidr: str) -> str:
        if ip_cidr.strip() == "*":
            return "*"
        try:
            net = ipaddress.IPv4Network(ip_cidr, strict=False)
            return str(net)
        except ipaddress.AddressValueError:
            pass
        try:
            net = ipaddress.IPv6Network(ip_cidr, strict=False)
            return str(net)
        except ipaddress.AddressValueError:
            raise ValidationError(f"无效的 IP/CIDR 格式: {ip_cidr}")

    async def _get_key(self, key_id: str) -> CallerPublicKey:
        key = await self.db.scalar(
            select(CallerPublicKey).where(CallerPublicKey.key_id == key_id)
        )
        if key is None:
            raise NotFoundError(f"公钥不存在: {key_id}")
        return key
