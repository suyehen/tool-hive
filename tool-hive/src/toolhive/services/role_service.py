"""后台角色与操作权限服务。"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import (
    SUPER_ADMIN_ROLE_NAME,
    OperationCode,
)
from toolhive.models.account_role import AccountRole
from toolhive.models.backend_role import BackendRole
from toolhive.models.management_operation import ManagementOperation
from toolhive.models.role_operation import RoleOperation

logger = logging.getLogger(__name__)


class RoleService:
    """后台角色与权限判定。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═════════════════════════════════════════════════════════════
    # 角色 CRUD
    # ═════════════════════════════════════════════════════════════

    async def list_roles(
        self, offset: int = 0, limit: int = 50,
    ) -> tuple[list[BackendRole], int]:
        result = await self.db.execute(
            select(BackendRole)
            .order_by(BackendRole.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list(result.scalars().all())
        total = await self.db.scalar(
            select(func.count()).select_from(BackendRole)
        )
        return items, total or 0

    async def get_role(self, role_id: str) -> BackendRole:
        role = await self.db.get(BackendRole, role_id)
        if role is None:
            raise NotFoundError(f"角色不存在: {role_id}")
        return role

    async def create_role(
        self, name: str, description: str | None = None,
    ) -> BackendRole:
        existing = await self.db.scalar(
            select(BackendRole).where(BackendRole.name == name)
        )
        if existing:
            raise ConflictError(f"角色名 '{name}' 已被使用")

        role = BackendRole(
            name=name,
            description=description,
            is_super_admin=(name == SUPER_ADMIN_ROLE_NAME),
        )
        self.db.add(role)
        await self.db.flush()
        return role

    async def update_role(
        self, role_id: str, name: str | None = None, description: str | None = None,
    ) -> BackendRole:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能修改超级管理员角色")

        if name and name != role.name:
            existing = await self.db.scalar(
                select(BackendRole).where(BackendRole.name == name)
            )
            if existing:
                raise ConflictError(f"角色名 '{name}' 已被使用")
            role.name = name

        if description is not None:
            role.description = description

        await self.db.flush()
        return role

    async def update_role_status(
        self, role_id: str, status: str,
    ) -> BackendRole:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能修改超级管理员角色状态")
        if status not in ("active", "disabled", "archived"):
            raise ValidationError(f"无效状态: {status}")
        role.status = status
        await self.db.flush()
        return role

    # ═════════════════════════════════════════════════════════════
    # 操作项分配
    # ═════════════════════════════════════════════════════════════

    async def get_role_operations(self, role_id: str) -> list[ManagementOperation]:
        await self.get_role(role_id)
        result = await self.db.execute(
            select(ManagementOperation)
            .join(RoleOperation, RoleOperation.operation_code == ManagementOperation.operation_code)
            .where(RoleOperation.role_id == role_id)
            .where(ManagementOperation.status == "active")
        )
        return list(result.scalars().all())

    async def assign_operations(
        self, role_id: str, operation_codes: list[str],
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("超级管理员自动拥有全部操作项，无需分配")

        for code in operation_codes:
            existing = await self.db.scalar(
                select(RoleOperation).where(
                    RoleOperation.role_id == role_id,
                    RoleOperation.operation_code == code,
                )
            )
            if not existing:
                op = RoleOperation(role_id=role_id, operation_code=code)
                self.db.add(op)
        await self.db.flush()

    async def remove_operations(
        self, role_id: str, operation_codes: list[str],
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            raise ValidationError("不能移除超级管理员的任何操作项")

        for code in operation_codes:
            existing = await self.db.scalar(
                select(RoleOperation).where(
                    RoleOperation.role_id == role_id,
                    RoleOperation.operation_code == code,
                )
            )
            if existing:
                await self.db.delete(existing)
        await self.db.flush()

    # ═════════════════════════════════════════════════════════════
    # 账号 — 角色关联
    # ═════════════════════════════════════════════════════════════

    async def get_account_roles(self, account_id: str) -> list[BackendRole]:
        result = await self.db.execute(
            select(BackendRole)
            .join(AccountRole, AccountRole.role_id == BackendRole.id)
            .where(AccountRole.account_id == account_id)
            .where(BackendRole.status == "active")
        )
        return list(result.scalars().all())

    async def assign_role_to_account(
        self, account_id: str, role_id: str, operator_id: str,
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            # 只有超管可以授予超管角色
            operator_roles = await self.get_account_roles(operator_id)
            if not any(r.is_super_admin for r in operator_roles):
                raise ValidationError("只有超级管理员可以授予超级管理员角色")

        existing = await self.db.scalar(
            select(AccountRole).where(
                AccountRole.account_id == account_id,
                AccountRole.role_id == role_id,
            )
        )
        if existing:
            raise ConflictError("该账号已拥有此角色")

        acct_role = AccountRole(account_id=account_id, role_id=role_id)
        self.db.add(acct_role)
        await self.db.flush()

    async def remove_role_from_account(
        self, account_id: str, role_id: str, operator_id: str,
    ) -> None:
        role = await self.get_role(role_id)
        if role.is_super_admin:
            operator_roles = await self.get_account_roles(operator_id)
            if not any(r.is_super_admin for r in operator_roles):
                raise ValidationError("只有超级管理员可以移除超级管理员角色")

            # 不允许移除最后一个超管的超管角色
            super_admin_role_ids = await self._get_super_admin_role_ids()
            all_super_admin_accounts = set()
            for sa_role_id in super_admin_role_ids:
                result = await self.db.execute(
                    select(AccountRole.account_id).where(
                        AccountRole.role_id == sa_role_id,
                    )
                )
                all_super_admin_accounts.update(r[0] for r in result)
            if len(all_super_admin_accounts) <= 1 and account_id in all_super_admin_accounts:
                raise ValidationError("不能移除最后一个超级管理员的超级管理员角色")

        ar = await self.db.scalar(
            select(AccountRole).where(
                AccountRole.account_id == account_id,
                AccountRole.role_id == role_id,
            )
        )
        if ar:
            await self.db.delete(ar)
            await self.db.flush()

    # ═════════════════════════════════════════════════════════════
    # 权限判定
    # ═════════════════════════════════════════════════════════════

    async def get_effective_operations(
        self, account_id: str,
    ) -> set[OperationCode]:
        """计算账号的有效管理操作项（所有角色所含操作码的并集）。"""
        roles = await self.get_account_roles(account_id)

        # 超管拥有全部有效操作项
        if any(r.is_super_admin for r in roles):
            result = await self.db.execute(
                select(ManagementOperation.operation_code).where(
                    ManagementOperation.status == "active"
                )
            )
            return {OperationCode(r[0]) for r in result}

        # 普通角色：收集所有操作码
        ops: set[OperationCode] = set()
        for role in roles:
            result = await self.db.execute(
                select(RoleOperation.operation_code).where(
                    RoleOperation.role_id == role.id,
                )
            )
            for row in result:
                try:
                    ops.add(OperationCode(row[0]))
                except ValueError:
                    logger.warning("无效操作码 in DB: %s", row[0])

        return ops

    async def check_operation(
        self, account_id: str, required: OperationCode,
    ) -> bool:
        return required in await self.get_effective_operations(account_id)

    # ═════════════════════════════════════════════════════════════
    # 启动同步
    # ═════════════════════════════════════════════════════════════

    async def sync_operation_codes(self) -> None:
        """启动时同步操作码到数据库（幂等）。"""
        all_codes = set(OperationCode)

        # 列出数据库中所有现有操作码
        result = await self.db.execute(select(ManagementOperation))
        db_codes: dict[str, ManagementOperation] = {
            r.operation_code: r for r in result.scalars().all()
        }

        # 新增操作码 → 插入
        for code in all_codes:
            if code not in db_codes:
                op = ManagementOperation(
                    operation_code=str(code),
                    display_name=str(code),  # 默认用 operation_code 作显示名
                    status="active",
                )
                self.db.add(op)
                logger.info("新增操作码: %s", code)

            # 授予超管
            super_admin_roles = await self._get_super_admin_role_ids()
            for sa_role_id in super_admin_roles:
                existing = await self.db.scalar(
                    select(RoleOperation).where(
                        RoleOperation.role_id == sa_role_id,
                        RoleOperation.operation_code == code,
                    )
                )
                if not existing:
                    self.db.add(RoleOperation(
                        role_id=sa_role_id,
                        operation_code=code,
                    ))

        # 废弃的操作码 → 标记（不删除）
        db_code_set = set(db_codes.keys())
        for code in db_code_set - all_codes:
            op = db_codes[code]
            if op.status != "deprecated":
                op.status = "deprecated"
                self.db.add(op)
                logger.info("废弃操作码: %s", code)

        await self.db.flush()

    async def ensure_super_admin_role(self) -> BackendRole:
        """确保超级管理员角色存在（首次启动时创建）。"""
        role = await self.db.scalar(
            select(BackendRole).where(BackendRole.name == SUPER_ADMIN_ROLE_NAME)
        )
        if role is None:
            role = BackendRole(
                name=SUPER_ADMIN_ROLE_NAME,
                description="内置超级管理员角色，不可删除、不可修改",
                is_super_admin=True,
                status="active",
            )
            self.db.add(role)
            await self.db.flush()
        return role

    # ═════════════════════════════════════════════════════════════
    # 内部
    # ═════════════════════════════════════════════════════════════

    async def _get_super_admin_role_ids(self) -> list[str]:
        result = await self.db.execute(
            select(BackendRole.id).where(BackendRole.is_super_admin == True)
        )
        return [r[0] for r in result]
