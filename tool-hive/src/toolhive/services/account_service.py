"""管理账号生命周期服务。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.config import AdminSecuritySettings
from toolhive.core.enums import AccountStatus
from toolhive.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from toolhive.infrastructure.transactions import transactional
from toolhive.models.account_role import AccountRole
from toolhive.models.management_account import ManagementAccount
from toolhive.services.audit_service import AuditService
from toolhive.services.role_service import RoleService
from toolhive.services.security.password import (
    generate_temp_password,
    hash_password,
    validate_password_strength,
    verify_password,
)
from toolhive.services.security.session import revoke_all_sessions

logger = logging.getLogger(__name__)


class AccountService:
    """管理账号生命周期操作。所有写操作强制校验守护规则。"""

    def __init__(self, db: AsyncSession, admin_security: AdminSecuritySettings):
        self.db = db
        self._admin_security = admin_security

    # ── 初始化 ──

    @transactional()
    async def init_super_admin(self, username: str, password: str) -> ManagementAccount:
        """CLI 调用：仅当无任何账号时创建首个超级管理员并授予超管角色。"""
        audit = AuditService(self.db)
        try:
            count = await self.db.scalar(
                select(func.count()).select_from(ManagementAccount)
            )
            if count and count > 0:
                raise ValidationError("已存在管理账号，不能重复初始化超管")
            violations = validate_password_strength(password, username)
            if violations:
                raise ValidationError("; ".join(violations))
            account = ManagementAccount(
                username=username,
                password_hash=hash_password(password),
                must_change_password=False,
            )
            self.db.add(account)
            await self.db.flush()

            # 确保内置超管角色存在，并建立账号 → 超管角色关联
            super_role = await RoleService(self.db).ensure_super_admin_role()
            self.db.add(AccountRole(account_id=account.id, role_id=super_role.id))
            await self.db.flush()

            audit.add_record(
                action="admin.init",
                object_type="account",
                object_id=account.id,
                actor_account_name=username,
                after_summary={"username": username, "role": "super_admin"},
            )
            logger.info(
                "首个超级管理员初始化完成: username=%s source=cli", username,
            )
            return account
        except ValidationError as exc:
            await AuditService.record_standalone(
                action="admin.init",
                object_type="account",
                actor_account_name=username,
                result="failure",
                reason=str(exc),
            )
            raise

    async def has_any_account(self) -> bool:
        """是否存在任意管理账号（用于初始化状态查询，不泄露账号信息）。"""
        count = await self.db.scalar(
            select(func.count()).select_from(ManagementAccount)
        )
        return bool(count and count > 0)

    # ── 创建 ──

    @transactional()
    async def create_account(
        self,
        username: str,
        external_user_id: str | None = None,
    ) -> tuple[ManagementAccount, str]:
        """创建新账号，返回 (账号对象, 临时密码)。"""
        # 检查用户名历史（不可重复分配给历史账号）
        existing = await self.db.scalar(
            select(ManagementAccount).where(ManagementAccount.username == username)
        )
        if existing:
            raise ConflictError(f"用户名 '{username}' 已被占用")

        if external_user_id:
            dup = await self.db.scalar(
                select(ManagementAccount).where(
                    ManagementAccount.external_user_id == external_user_id
                )
            )
            if dup:
                raise ConflictError(f"工号 '{external_user_id}' 已被绑定")

        temp_pwd = generate_temp_password()
        violations = validate_password_strength(temp_pwd, username, external_user_id)
        if violations:
            raise ValidationError("; ".join(violations))

        account = ManagementAccount(
            username=username,
            password_hash=hash_password(temp_pwd),
            external_user_id=external_user_id,
            must_change_password=True,
            temp_password_expires_at=datetime.now(UTC)
            + timedelta(hours=self._admin_security.temp_password_expire_hours),
        )
        self.db.add(account)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account.create",
            object_type="account",
            object_id=account.id,
            after_summary={"username": username, "external_user_id": external_user_id},
        )
        return account, temp_pwd

    # ── 查询 ──

    async def get_by_id(self, account_id: str) -> ManagementAccount:
        account = await self.db.get(ManagementAccount, account_id)
        if account is None:
            raise NotFoundError(f"账号不存在: {account_id}")
        return account

    async def get_by_username(self, username: str) -> ManagementAccount | None:
        return await self.db.scalar(
            select(ManagementAccount).where(ManagementAccount.username == username)
        )

    async def list_accounts(
        self, offset: int = 0, limit: int = 50,
    ) -> tuple[list[ManagementAccount], int]:
        """分页列出账号。返回 (列表, 总数)。"""
        total = await self.db.scalar(
            select(func.count()).select_from(ManagementAccount)
        )
        result = await self.db.execute(
            select(ManagementAccount)
            .order_by(ManagementAccount.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    # ── 密码 ──

    @transactional()
    async def update_password(
        self, account: ManagementAccount, old_password: str, new_password: str,
    ) -> None:
        """用户修改自己的密码。"""
        is_valid, _ = verify_password(old_password, account.password_hash)
        if not is_valid:
            raise AuthenticationError("当前密码不正确")

        await self._set_password(account, new_password)
        account.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account.change_password",
            object_type="account",
            object_id=account.id,
            after_summary={"must_change_password": False},
        )

    @transactional()
    async def reset_password(
        self, account: ManagementAccount,
    ) -> str:
        """管理员重置他人密码，返回临时密码。"""
        temp_pwd = generate_temp_password()
        violations = validate_password_strength(
            temp_pwd, account.username, account.external_user_id,
        )
        if violations:
            raise ValidationError("; ".join(violations))

        account.password_hash = hash_password(temp_pwd)
        account.must_change_password = True
        account.temp_password_expires_at = datetime.now(UTC) + timedelta(
            hours=self._admin_security.temp_password_expire_hours
        )
        account.security_version += 1
        account.row_version += 1

        # 立即撤销该账号全部会话
        await revoke_all_sessions(account.id)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account.reset_password",
            object_type="account",
            object_id=account.id,
            after_summary={"must_change_password": True},
        )
        return temp_pwd

    # ── 状态控制 ──

    @transactional()
    async def enable_account(self, account: ManagementAccount) -> None:
        if account.status == AccountStatus.ENABLED:
            raise ConflictError("账号已启用")
        account.status = AccountStatus.ENABLED
        account.locked_until = None
        account.login_failures = 0
        account.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account.enable",
            object_type="account",
            object_id=account.id,
            after_summary={"status": "enabled"},
        )

    @transactional()
    async def disable_account(
        self, account: ManagementAccount, operator_id: str,
    ) -> None:
        """禁用账号。不允许禁用最后一个超管，不允许禁用自己。"""
        try:
            if account.id == operator_id:
                raise ValidationError("不能停用自己的账号")
            if account.status == AccountStatus.DISABLED:
                raise ConflictError("账号已禁用")
            await self._check_last_super_admin(account)
            account.status = AccountStatus.DISABLED
            account.security_version += 1
            account.row_version += 1
            await revoke_all_sessions(account.id)
            await self.db.flush()
        except ValidationError as exc:
            await AuditService.record_standalone(
                action="account.disable",
                object_type="account",
                object_id=account.id,
                result="failure",
                reason=str(exc),
            )
            raise
        AuditService(self.db).add_record(
            action="account.disable",
            object_type="account",
            object_id=account.id,
            after_summary={"status": "disabled"},
        )

    @transactional()
    async def unlock_account(self, account: ManagementAccount) -> None:
        """提前解锁账号。"""
        account.status = AccountStatus.ENABLED
        account.login_failures = 0
        account.locked_until = None
        account.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="account.unlock",
            object_type="account",
            object_id=account.id,
            after_summary={"status": "enabled", "locked_until": None},
        )

    @transactional()
    async def offboard_account(
        self, account: ManagementAccount, operator_id: str,
    ) -> None:
        """离职处理：禁用 + 撤销全部会话 + 保留记录。"""
        try:
            if account.id == operator_id:
                raise ValidationError("不能对自己执行离职处理")
            await self._check_last_super_admin(account)
            account.status = AccountStatus.DISABLED
            account.security_version += 1
            account.row_version += 1
            await revoke_all_sessions(account.id)
            await self.db.flush()
        except ValidationError as exc:
            await AuditService.record_standalone(
                action="account.offboard",
                object_type="account",
                object_id=account.id,
                result="failure",
                reason=str(exc),
            )
            raise
        AuditService(self.db).add_record(
            action="account.offboard",
            object_type="account",
            object_id=account.id,
            after_summary={"status": "disabled"},
        )

    @transactional()
    async def force_logout(self, account: ManagementAccount) -> None:
        """强制下线：撤销全部会话。"""
        await revoke_all_sessions(account.id)
        AuditService(self.db).add_record(
            action="account.force_logout",
            object_type="account",
            object_id=account.id,
        )

    # ── 登录安全计数 ──

    @transactional(requires_new=True)
    async def record_login_failure(self, account: ManagementAccount) -> None:
        """记录一次登录失败，检查是否需要锁定。

        使用独立事务提交，保证请求最终返回认证失败时，
        失败计数与锁定状态仍然持久化。
        """
        fresh = await self.db.get(ManagementAccount, account.id)
        if fresh is None:
            return
        fresh.login_failures += 1
        if fresh.login_failures >= self._admin_security.login_max_failures:
            fresh.status = AccountStatus.LOCKED
            fresh.locked_until = datetime.now(UTC) + timedelta(
                minutes=self._admin_security.login_lock_minutes,
            )
        await self.db.flush()

    @transactional()
    async def record_login_success(self, account: ManagementAccount) -> None:
        """登录成功：清空失败计数，自动解除锁定状态。"""
        account.login_failures = 0
        if account.status == AccountStatus.LOCKED:
            account.status = AccountStatus.ENABLED
        account.locked_until = None
        await self.db.flush()

    # ── 内部方法 ──

    async def _set_password(self, account: ManagementAccount, new_password: str) -> None:
        """内部：设置新密码并检查历史。"""
        from sqlalchemy import desc, select

        from toolhive.models.password_history import PasswordHistory

        violations = validate_password_strength(
            new_password, account.username, account.external_user_id,
        )
        if violations:
            raise ValidationError("; ".join(violations))

        # 检查密码历史
        result = await self.db.execute(
            select(PasswordHistory)
            .where(PasswordHistory.account_id == account.id)
            .order_by(desc(PasswordHistory.create_time))
            .limit(self._admin_security.password_history_count)
        )
        recent = result.scalars().all()
        for entry in recent:
            is_match, _ = verify_password(new_password, entry.password_hash)
            if is_match:
                raise ValidationError(
                    f"不能与最近 {self._admin_security.password_history_count} 次密码相同"
                )

        # 写入密码历史
        history = PasswordHistory(
            account_id=account.id,
            password_hash=hash_password(new_password),
        )
        self.db.add(history)

        # 更新账号密码
        account.password_hash = hash_password(new_password)
        account.must_change_password = False
        account.temp_password_expires_at = None

    async def _check_last_super_admin(self, account: ManagementAccount) -> None:
        """检查是否为最后一个启用状态的超管，防止系统失去管理入口。"""
        if account.status == AccountStatus.DISABLED:
            return
        role_svc = RoleService(self.db)
        if not await role_svc.is_super_admin_account(account.id):
            return
        if await role_svc.count_enabled_super_admins() <= 1:
            raise ValidationError("不能停用或离职最后一个超级管理员")
