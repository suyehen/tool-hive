"""调用系统管理服务。"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.constants import CALLER_SYSTEM_ID_PREFIX
from toolhive.core.enums import (
    CallerSystemStatus,
    IPRuleStatus,
    PublicKeyStatus,
)
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.caller_ip_rule import CallerIPRule
from toolhive.models.caller_public_key import CallerPublicKey
from toolhive.models.caller_system import CallerSystem

logger = logging.getLogger(__name__)


class CallerSystemService:
    """调用系统生命周期管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

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
        environment: str,
        description: str | None = None,
        department: str | None = None,
        owner: str | None = None,
        contact: str | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> CallerSystem:
        if environment not in ("development", "production"):
            raise ValidationError("环境必须是 development 或 production")

        system = CallerSystem(
            system_id=self.generate_system_id(),
            name=name,
            description=description,
            environment=environment,
            department=department,
            owner=owner,
            contact=contact,
            status=CallerSystemStatus.DRAFT,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        self.db.add(system)
        await self.db.flush()
        return system

    @transactional()
    async def update_system(
        self,
        system_id: str,
        name: str | None = None,
        description: str | None = None,
        department: str | None = None,
        owner: str | None = None,
        contact: str | None = None,
        effective_from: datetime | None = None,
        effective_to: datetime | None = None,
    ) -> CallerSystem:
        """更新调用系统主记录（仅更新显式提供的字段）。"""
        system = await self.get_by_system_id(system_id)
        if name is not None:
            system.name = name
        if description is not None:
            system.description = description
        if department is not None:
            system.department = department
        if owner is not None:
            system.owner = owner
        if contact is not None:
            system.contact = contact
        if effective_from is not None:
            system.effective_from = effective_from
        if effective_to is not None:
            system.effective_to = effective_to
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

        # 检查有效期
        if system.effective_to and system.effective_to <= datetime.now(timezone.utc):
            raise ValidationError("当前时间不在有效期内")

        system.status = CallerSystemStatus.ENABLED
        await self.db.flush()
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
        await self.db.flush()
        return system

    @transactional()
    async def revive(self, system_id: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status != CallerSystemStatus.DISABLED:
            raise ConflictError("只有已停用的调用系统可以恢复")
        system.status = CallerSystemStatus.ENABLED
        system.deactivated_reason = None
        await self.db.flush()
        return system

    @transactional()
    async def revoke(self, system_id: str, reason: str) -> CallerSystem:
        system = await self.get_by_system_id(system_id)
        if system.status == CallerSystemStatus.REVOKED:
            raise ConflictError("调用系统已注销")
        system.status = CallerSystemStatus.REVOKED
        system.deactivated_reason = reason
        # 撤销全部公钥
        keys = await self.list_public_keys(system_id)
        for key in keys:
            if key.status not in (
                PublicKeyStatus.REVOKED,
                PublicKeyStatus.EXPIRED,
            ):
                key.status = PublicKeyStatus.REVOKED
                self.db.add(key)
        await self.db.flush()
        return system

    @transactional()
    async def check_and_expire(self, system_id: str) -> None:
        """超过 effective_to 自动拒绝请求（调用方检查）。"""
        system = await self.get_by_system_id(system_id)
        if system.effective_to and system.effective_to <= datetime.now(timezone.utc):
            if system.status == CallerSystemStatus.ENABLED:
                system.status = CallerSystemStatus.DISABLED
                system.deactivated_reason = "已过期（自动）"
                await self.db.flush()

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
        self, offset: int = 0, limit: int = 50,
    ) -> tuple[list[CallerSystem], int]:
        result = await self.db.execute(
            select(CallerSystem)
            .order_by(CallerSystem.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(result.scalars().all())
        total = await self.db.scalar(
            select(func.count()).select_from(CallerSystem)
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

        key = CallerPublicKey(
            key_id=self.generate_key_id(),
            system_id=system_id,
            public_key=public_key,
            fingerprint=fingerprint,
            algorithm=algorithm,
            status=PublicKeyStatus.PENDING,
            effective_from=datetime.now(timezone.utc),
            effective_to=effective_to,
        )
        self.db.add(key)
        await self.db.flush()
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
        await self.db.flush()
        return key

    @transactional()
    async def disable_public_key(self, key_id: str) -> CallerPublicKey:
        key = await self._get_key(key_id)
        if key.status not in (PublicKeyStatus.PENDING, PublicKeyStatus.ACTIVE):
            raise ConflictError("只能停用有效或待启用状态的公钥")
        key.status = PublicKeyStatus.DISABLED
        await self.db.flush()
        return key

    @transactional()
    async def revoke_public_key(self, key_id: str) -> CallerPublicKey:
        key = await self._get_key(key_id)
        if key.status == PublicKeyStatus.REVOKED:
            raise ConflictError("该公钥已撤销")
        key.status = PublicKeyStatus.REVOKED
        await self.db.flush()
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
        rule = CallerIPRule(
            system_id=system_id,
            ip_cidr=normalized,
            description=description,
        )
        self.db.add(rule)
        await self.db.flush()
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
        await self.db.flush()
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
